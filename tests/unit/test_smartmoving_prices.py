"""A job signed on the customer page has no SmartMoving prices: deleted at the signature, and once for jobs signed before."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, EstimateSignature, Lead, LeadJob, LeadJobCharge
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Lead(id='signed-lead', full_name='Gabrielle Taylor', estimated_total=json.dumps({'subtotal': 3571.4, 'taxableAmount': 100, 'tax': 7, 'finalTotal': 3407})),
                    Lead(id='open-lead', full_name='Pat Quote', estimated_total=json.dumps({'subtotal': 900, 'taxableAmount': 0, 'tax': 0, 'finalTotal': 900}))])
        db.flush()
        db.add_all([LeadJob(id='signed', lead_id='signed-lead', job_order=1, price=1801, smartmoving_price=3400),
                    LeadJob(id='open', lead_id='open-lead', job_order=1, smartmoving_price=900)])
        db.flush()
        db.add_all([LeadJobCharge(job_id='signed', name='SmartMoving moving', total_cost=3400, subtotal=3571.4, discount_amount=171.4, source='smartmoving'),
                    LeadJobCharge(job_id='signed', name='Transportation', total_cost=1801, subtotal=1972.4, discount_amount=171.4, source='crm'),
                    LeadJobCharge(job_id='open', name='SmartMoving moving', total_cost=900, subtotal=900, source='smartmoving'),
                    EstimateSignature(lead_id='signed-lead', job_id='signed', snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 16))])
        db.commit()
    return engine


def test_jobs_signed_before_lose_their_smartmoving_prices_once():
    from sqlalchemy.orm import Session
    from models import Lead, LeadJob, LeadJobCharge
    from smartmoving_prices import drop_signed_smartmoving_prices
    engine = make_db()
    with engine.begin() as connection:
        assert drop_signed_smartmoving_prices(connection) == 1
    with Session(engine) as db:
        assert [c.name for c in db.query(LeadJobCharge).filter_by(job_id='signed')] == ['Transportation']
        assert db.get(LeadJob, 'signed').smartmoving_price is None
        assert json.loads(db.get(Lead, 'signed-lead').estimated_total) == {'subtotal': 1972.4, 'taxableAmount': 0.0, 'tax': 0.0, 'finalTotal': 1801.0}
        # A job not signed keeps SmartMoving's prices.
        assert db.query(LeadJobCharge).filter_by(job_id='open').count() == 1
        assert db.get(LeadJob, 'open').smartmoving_price == 900
        assert json.loads(db.get(Lead, 'open-lead').estimated_total)['finalTotal'] == 900
    engine.dispose()


def test_signing_keeps_the_reps_approval():
    from sqlalchemy.orm import Session
    import estimate_approval  # noqa: F401  The hook that clears approvals on estimate changes.
    from models import Lead, LeadJob
    from smartmoving_prices import drop_smartmoving_prices
    engine = make_db()
    with Session(engine) as db:
        job = db.get(LeadJob, 'signed')
        job.estimate_approved_id = 'approved-copy'
        db.commit()
        db.get(Lead, 'signed-lead')
        drop_smartmoving_prices(db, job)
        db.commit()
        assert db.get(LeadJob, 'signed').estimate_approved_id == 'approved-copy'
        assert json.loads(db.get(Lead, 'signed-lead').estimated_total)['finalTotal'] == 1801.0
    engine.dispose()


def test_signed_leads_are_detached_from_smartmoving_once():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, DetachedSmartMovingLead, EstimateSignature, Lead, LeadJob
    from smartmoving_prices import detach_signed_leads
    engine = create_engine('sqlite://')
    # The deploy step creates the table itself.
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name != DetachedSmartMovingLead.__tablename__])
    with Session(engine) as db:
        db.add_all([Lead(id='signed', full_name='A', smartmoving_id='sm-signed'), Lead(id='open', full_name='B', smartmoving_id='sm-open')])
        db.flush()
        db.add(LeadJob(id='job', lead_id='signed', job_order=1))
        db.flush()
        db.add(EstimateSignature(lead_id='signed', job_id='job', snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 16)))
        db.commit()
    with engine.begin() as connection:
        assert detach_signed_leads(connection) == 1
    with engine.begin() as connection:
        assert detach_signed_leads(connection) == 0  # Nothing left to detach.
    with Session(engine) as db:
        assert db.get(Lead, 'signed').smartmoving_id is None
        assert db.get(Lead, 'open').smartmoving_id == 'sm-open'
        assert db.get(DetachedSmartMovingLead, 'sm-signed').lead_id == 'signed'
    engine.dispose()


def test_a_detached_smartmoving_lead_is_not_created_again(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, DetachedSmartMovingLead, Lead
    for name in list(sys.modules):
        if name in ('database', 'routes.leads', 'libs') or name.startswith('libs.'):
            monkeypatch.delitem(sys.modules, name)
    import importlib
    leads = importlib.import_module('routes.leads')
    monkeypatch.setattr(leads, 'get_config', lambda: {'API_SECRET': 'secret'})
    monkeypatch.setattr(leads, '_hydrate_new_lead_from_smartmoving', lambda body: pytest.fail('SmartMoving was asked'))
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Lead(id='signed', full_name='A'))
        db.flush()
        db.add(DetachedSmartMovingLead(smartmoving_id='sm-signed', lead_id='signed'))
        db.commit()
        body = leads.NewLead.model_validate({'full_name': 'A', 'company_name': 'X', 'source': 'SmartMoving', 'smartmoving_id': 'sm-signed'})
        with pytest.raises(HTTPException) as refused:
            leads._create_lead(body, 'secret', db)
        assert refused.value.status_code == 409
    engine.dispose()
