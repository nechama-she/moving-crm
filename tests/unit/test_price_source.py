"""Each job has one price, ours or SmartMoving's (price_source), and every total counts only that price's lines; the
automatic refresh never gives a job priced by SmartMoving a price of ours."""
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

OURS = [('Transportation charge', '7862.50'), ('Fuel surcharge', '1022.12')]
THEIRS = [('Flat rate, Direct delivery', '5295.00'), ('one extra night', '300.00')]


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def lead_with(db, status, ours=(), theirs=(), signed=False, lead_id='lead'):
    from models import EstimateSignature, Lead, LeadJob, LeadJobCharge
    db.add(Lead(id=lead_id, full_name='Customer', status=status))
    db.flush()
    job = LeadJob(id=f'{lead_id}-job', lead_id=lead_id, job_order=1, price=Decimal('1'))
    job.charges = [LeadJobCharge(id=f'{lead_id}-{source}-{index}', name=name, sort_order=index, subtotal=Decimal(total),
                                 total_cost=Decimal(total), discount_amount=0, source=source)
                   for source, lines in (('crm', ours), ('smartmoving', theirs)) for index, (name, total) in enumerate(lines)]
    db.add(job)
    if signed:
        db.add(EstimateSignature(lead_id=lead_id, job_id=job.id, snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 1)))
    db.commit()
    return db.get(Lead, lead_id), job


CASES = [
    # (status, ours, theirs, signed, the job's price, its total)
    ('new', OURS, THEIRS, False, 'crm', '8884.62'),        # Not booked, priced by us: ours only.
    ('quoted', (), THEIRS, False, 'smartmoving', '5595.00'),  # Not booked, not priced by us: SmartMoving's.
    ('booked', OURS, THEIRS, False, 'smartmoving', '5595.00'),  # Booked, not signed with us: SmartMoving's.
    ('booked', OURS, (), False, 'crm', '8884.62'),          # Booked in the CRM with no SmartMoving price: ours.
    ('booked', OURS, (), True, 'crm', '8884.62'),           # Signed with us: ours.
]


@pytest.mark.parametrize('status,ours,theirs,signed,source,total', CASES)
def test_every_total_counts_only_the_jobs_price(db, status, ours, theirs, signed, source, total):
    import json
    from models import Lead, lead_estimated_total
    from price_source import counted_charges, job_price_source
    from routes.leads import _refresh_lead_estimated_total, _serialize_job_with_addresses
    lead, job = lead_with(db, status, ours, theirs, signed)
    assert job_price_source(lead, job, signed) == source
    assert str(sum(c.total_cost for c in counted_charges(lead, job, signed))) == total
    # The lead page's Charges box gets only those lines, and the lead's totals add up only them.
    page = _serialize_job_with_addresses(job, db)
    assert page['price_source'] == source and f"{sum(Decimal(str(c['total_cost'])) for c in page['charges']):.2f}" == total
    _refresh_lead_estimated_total('lead', db)
    db.commit()
    db.expire_all()
    lead = db.get(Lead, 'lead')
    assert f"{json.loads(lead.estimated_total)['finalTotal']:.2f}" == total
    assert f"{lead_estimated_total(lead.lines_total, lead.lines_discount, lead.lineless_prices, None)['finalTotal']:.2f}" == total


@pytest.mark.parametrize('status,ours,theirs', [('booked', (), THEIRS), ('booked', OURS, THEIRS), ('new', (), THEIRS)])
def test_the_refresh_never_prices_a_job_priced_by_smartmoving(db, monkeypatch, status, ours, theirs):
    from price_validity import refresh_expired_price
    lead, job = lead_with(db, status, ours, theirs)
    job.price_calculated_at = datetime.utcnow() - timedelta(days=60)
    db.commit()
    import routes.pricing as pricing
    called = []
    monkeypatch.setattr(pricing, 'calculate_and_save_lead_job_price', lambda *args: called.append(args))
    assert refresh_expired_price(lead, job, db) is False and called == []
