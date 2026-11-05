"""The transportation subtotal discount, through the real endpoints and totals: set, recalculate, change, remove."""
import os
import sys
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

BASE = [('Transportation charge', '1875', '$7.50 per cu ft (minimum charge $1,875.00)'),
        ('Fuel surcharge', '243.75', '13% fuel surcharge'), ('Origin destination & administration Fee', '199', '$199.00 per job')]


def test_subtotal_discount_applies_to_all_three_and_removes_from_all_three(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Lead, LeadJob, LeadJobCharge, PublicMoveAccess
    from routes import public_moves
    from charge_updates import ChargeUpdates
    from routes.leads import _refresh_lead_estimated_total
    import price_validity
    monkeypatch.setattr(public_moves, 'is_rep_request', lambda access, request: True)
    monkeypatch.setattr(price_validity, 'price_is_locked', lambda lead, job: False)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Lead(id='lead', full_name='Customer', volume=235))
        job = LeadJob(id='job', lead_id='lead', job_order=1, customer_packing_package='{}')
        job.charges = [LeadJobCharge(id=str(uuid.uuid4()), name=name, sort_order=index, subtotal=Decimal(total), total_cost=Decimal(total),
                                     discount_amount=0, description=description, source='crm')
                       for index, (name, total, description) in enumerate(BASE)]
        db.add(job)
        db.add(PublicMoveAccess(id='access', lead_id='lead', job_id='job', key_hash='k' * 64, request_hash='r' * 64,
                                token_hash='t' * 64, expires_at=datetime(2030, 1, 1)))
        db.commit()
        access = db.get(PublicMoveAccess, 'access')

        def save(**body):
            fields = {'charge_id': 'package', 'title': 'Spring', 'type': 'amount', 'value': Decimal(0), 'remove': False, **body}
            return public_moves.save_rep_discount(SimpleNamespace(**fields), None, access, db)

        def totals():
            db.expire_all()
            return [str(row.total_cost) for row in db.get(LeadJob, 'job').charges]

        def read_back():
            return next(row for row in public_moves.rep_discount_options(None, access, db)['charges'] if row['id'] == 'package')['discount']

        assert save(type='percent', value=Decimal('10'))['price'] == '2085.97'
        assert totals() == ['1687.50', '219.37', '179.10']
        assert read_back()['type'] == 'percent'
        # A recalculation keeps the discount on all three.
        updates = ChargeUpdates(db, db.query(LeadJobCharge).filter_by(job_id='job').all(), match_legacy_base=True, remove_missing=False)
        for index, (name, total, description) in enumerate(BASE):
            updates.add(LeadJobCharge(id=str(uuid.uuid4()), job_id='job', name=name, description=description, sort_order=index,
                                      subtotal=Decimal(total), discount_amount=Decimal(0), total_cost=Decimal(total)))
        updates.finish()
        _refresh_lead_estimated_total('lead', db)
        db.commit()
        assert totals() == ['1687.50', '219.37', '179.10']
        assert save(type='amount', value=Decimal('150'))['price'] == '2167.75'
        assert save(type='total', value=Decimal('2000'))['price'] == '2000.00'
        # Remove puts all three back, descriptions included.
        assert save(remove=True)['price'] == '2317.75'
        assert totals() == ['1875.00', '243.75', '199.00']
        assert [row.description for row in db.get(LeadJob, 'job').charges] == [description for _, _, description in BASE]
        assert read_back() is None
    engine.dispose()
