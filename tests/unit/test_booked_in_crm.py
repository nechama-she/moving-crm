"""Booking a lead in the CRM sets its booked date to today, by the company's clock, as SmartMoving's sync does."""
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_booking_in_the_crm_sets_the_booked_date(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, Company, Lead, LeadJob, UserCompany, User
    for name in list(sys.modules):
        if name in ('database', 'routes.leads', 'libs') or name.startswith('libs.'):
            monkeypatch.delitem(sys.modules, name)
    import importlib
    leads = importlib.import_module('routes.leads')
    for hook in ('_sync_smartmoving_job_details', 'publish_realtime_event'):
        monkeypatch.setattr(leads, hook, lambda *args, **kwargs: None)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Company(id='co', name='Movers 95', timezone='America/New_York'))
        db.add(User(id='rep', name='Rep', email='rep@example.com', password_hash='x', role='admin'))
        db.flush()
        db.add(UserCompany(user_id='rep', company_id='co'))
        db.add(Lead(id='lead', full_name='A', company_id='co', status='quoted'))
        db.flush()
        db.add(LeadJob(id='job', lead_id='lead', job_order=1, company_id='co'))
        db.commit()
        user = db.get(User, 'rep')
        leads._apply_lead_update('lead', leads.LeadUpdate(status='booked'), user, db)
        db.expire_all()
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo('America/New_York')).date()
        assert db.get(Lead, 'lead').booked_move_date == today
        assert db.get(LeadJob, 'job').booked_move_date == today
        # Moved back off booked: the lead and its jobs no longer have a booked date, and the price is not locked.
        leads._apply_lead_update('lead', leads.LeadUpdate(status='new'), user, db)
        db.expire_all()
        from price_validity import price_is_locked
        lead, job = db.get(Lead, 'lead'), db.get(LeadJob, 'job')
        assert lead.booked_move_date is None and job.booked_move_date is None
        assert not price_is_locked(lead, job)
        # A booked date sent for a lead that is not booked is not kept.
        leads._apply_lead_update('lead', leads.LeadUpdate(booked_move_date='2026-11-20'), user, db)
        db.expire_all()
        assert db.get(Lead, 'lead').booked_move_date is None
    engine.dispose()
