"""A rep's discount on a fee tab: saved with the amount it takes off the tab's total, counted in the job's price and the
lead's total like any discount, and apart from the discounts on the tab's lines."""
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

LINES = [('Transportation charge', '1875'), ('Elevator', '250'), ('Pickup stairs', '100'), ('Delivery stairs', '60')]


@pytest.fixture
def move(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Lead, LeadJob, LeadJobCharge, PublicMoveAccess
    from routes import public_moves
    monkeypatch.setattr(public_moves, 'is_rep_request', lambda access, request: True)
    # The move has elevator and stairs questions, so those lines are on their tabs.
    monkeypatch.setattr(public_moves, '_customer_pricing_options', lambda lead, job, db: {'elevator': {}, 'stairs': {}})
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Lead(id='lead', full_name='Customer', volume=235))
        job = LeadJob(id='job', lead_id='lead', job_order=1, customer_packing_package='{}')
        job.charges = [LeadJobCharge(id=f'line{index}', name=name, sort_order=index, subtotal=Decimal(total),
                                     total_cost=Decimal(total), discount_amount=0, description='', source='crm')
                       for index, (name, total) in enumerate(LINES)]
        db.add(job)
        db.add(PublicMoveAccess(id='access', lead_id='lead', job_id='job', key_hash='k' * 64, request_hash='r' * 64,
                                token_hash='t' * 64, expires_at=datetime(2030, 1, 1)))
        db.commit()
        yield public_moves, db, db.get(PublicMoveAccess, 'access')
    engine.dispose()


def tab(mod, db, access, **body):
    fields = {'tab': 'stairs:', 'title': 'Stairs deal', 'type': 'amount', 'value': Decimal(0), 'remove': False, **body}
    return mod.save_section_discount(SimpleNamespace(**fields), None, access, db)


def line(mod, db, access, **body):
    fields = {'charge_id': 'line2', 'title': 'Pickup deal', 'type': 'amount', 'value': Decimal(0), 'remove': False, **body}
    return mod.save_rep_discount(SimpleNamespace(**fields), None, access, db)


def saved(db):
    """The job's saved price, the lead's saved total, the total the lead lists add up, and the stairs lines."""
    import json
    from models import Lead, LeadJob, lead_estimated_total
    db.expire_all()
    lead, job = db.get(Lead, 'lead'), db.get(LeadJob, 'job')
    listed = lead_estimated_total(lead.lines_total, lead.lines_discount, lead.lineless_prices, lead.estimated_total)
    stairs = [str(row.total_cost) for row in job.charges if 'stairs' in row.name]
    return str(job.price), json.loads(lead.estimated_total)['finalTotal'], listed['finalTotal'], stairs


def test_a_tab_discount_is_its_own_and_counts_everywhere(move):
    mod, db, access = move
    result = tab(mod, db, access, type='percent', value=Decimal('10'))
    # 10% of the stairs tab (160): $16 off the job, the lead and what the lead lists add up; the lines are untouched.
    assert result['price'] == '2269.00'
    assert result['tab_discounts'] == {'stairs:': {'title': 'Stairs deal', 'type': 'percent', 'value': 10.0, 'amount': 16.0}}
    assert saved(db) == ('2269.00', 2269.0, 2269.0, ['100.00', '60.00'])
    # A line's own discount: the tab's stays, now 10% of the tab as its lines show.
    result = line(mod, db, access, value=Decimal('40'))
    assert result['tab_discounts']['stairs:']['amount'] == 12.0
    assert saved(db) == ('2233.00', 2233.0, 2233.0, ['60.00', '60.00'])
    # Changing the tab's discount leaves the line's alone, and the other way round.
    tab(mod, db, access, type='amount', value=Decimal('20'))
    assert saved(db) == ('2225.00', 2225.0, 2225.0, ['60.00', '60.00'])
    line(mod, db, access, remove=True)
    assert saved(db) == ('2265.00', 2265.0, 2265.0, ['100.00', '60.00'])
    # Removed: nothing left behind.
    result = tab(mod, db, access, remove=True)
    assert result['tab_discounts'] == {} and saved(db) == ('2285.00', 2285.0, 2285.0, ['100.00', '60.00'])


def test_the_amount_follows_the_tab_when_its_lines_change(move):
    from models import LeadJobCharge
    from routes.leads import _refresh_lead_estimated_total
    mod, db, access = move
    tab(mod, db, access, type='percent', value=Decimal('50'))
    db.get(LeadJobCharge, 'line2').total_cost = Decimal('200')
    _refresh_lead_estimated_total('lead', db)
    db.commit()
    assert saved(db)[0] == '2255.00'  # 1875 + 250 + 200 + 60 - 50% of 260


def test_an_amount_is_never_more_than_the_tab(move):
    mod, db, access = move
    assert tab(mod, db, access, value=Decimal('500'))['tab_discounts']['stairs:']['amount'] == 160.0
