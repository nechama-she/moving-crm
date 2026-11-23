"""Disconnect a lead from SmartMoving and reconnect it: the id is kept aside, never lost, and only its own lead takes it
back, never after a signed estimate."""
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

SM_ID = '510d2dcf-3c22-4d9e-846c-b4ef011e65da'


@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import routes.leads as leads
    from models import Base, Lead, LeadJob
    monkeypatch.setattr(leads, '_lookup_sender_id', lambda lead: None)
    monkeypatch.setattr(leads, '_get_user_company_ids', lambda user, db: [])
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Lead(id='lead', full_name='Customer', smartmoving_id=SM_ID))
        session.flush()
        session.add(LeadJob(id='job', lead_id='lead', job_order=1))
        session.commit()
        yield session
    engine.dispose()


ADMIN = SimpleNamespace(id='admin', role='admin')


def test_disconnect_keeps_the_id_and_reconnect_puts_it_back(db):
    from routes.leads import disconnect_from_smartmoving, reconnect_to_smartmoving
    from models import DetachedSmartMovingLead, Lead
    page = disconnect_from_smartmoving('lead', ADMIN, db)
    assert page['smartmoving_id'] == '' and page['smartmoving_reconnect_id'] == SM_ID
    assert db.get(DetachedSmartMovingLead, SM_ID).lead_id == 'lead'
    page = reconnect_to_smartmoving('lead', ADMIN, db)
    assert page['smartmoving_id'] == SM_ID and page['smartmoving_reconnect_id'] == ''
    assert db.get(DetachedSmartMovingLead, SM_ID) is None and db.get(Lead, 'lead').smartmoving_id == SM_ID


def test_a_signed_lead_is_not_reconnected(db):
    from routes.leads import disconnect_from_smartmoving, reconnect_to_smartmoving
    from models import EstimateSignature
    disconnect_from_smartmoving('lead', ADMIN, db)
    db.add(EstimateSignature(lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 1)))
    db.commit()
    with pytest.raises(HTTPException) as error:
        reconnect_to_smartmoving('lead', ADMIN, db)
    assert error.value.status_code == 409


def test_only_admins_disconnect(db):
    from routes.leads import disconnect_from_smartmoving
    with pytest.raises(HTTPException) as error:
        disconnect_from_smartmoving('lead', SimpleNamespace(id='rep', role='sales_rep'), db)
    assert error.value.status_code == 403
