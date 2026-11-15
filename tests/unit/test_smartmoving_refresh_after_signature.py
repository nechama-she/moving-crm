"""A signed estimate ends the SmartMoving sync for its lead."""
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_signed_estimate_stops_smartmoving_refresh(monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, EstimateSignature, Lead, LeadJob
    from routes import leads
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    calls = []
    monkeypatch.setattr(leads, 'get_opportunity', lambda smartmoving_id: calls.append(smartmoving_id) or {'error': 'stop here'})
    monkeypatch.setattr(leads, '_get_visible_lead_or_404', lambda lead_id, user, db: db.get(Lead, lead_id))
    monkeypatch.setattr(leads, 'record_lead_update_log', lambda **kwargs: None)
    user = SimpleNamespace(id='rep', name='Rep', role='sales_rep')
    with Session(engine) as db:
        db.add(Lead(id='lead', full_name='Customer', smartmoving_id='sm-1'))
        db.add(LeadJob(id='job', lead_id='lead', job_order=1))
        db.add(EstimateSignature(id='estimate', lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF'))
        db.commit()
        # Not signed yet: the refresh still asks SmartMoving.
        with pytest.raises(HTTPException) as unsigned:
            leads._refresh_lead_from_smartmoving('lead', None, user, db, [])
        assert unsigned.value.status_code == 502 and calls == ['sm-1']
        # Signed: refused before SmartMoving is asked.
        db.get(EstimateSignature, 'estimate').signed_at = datetime(2026, 11, 15)
        db.commit()
        with pytest.raises(HTTPException) as signed:
            leads._refresh_lead_from_smartmoving('lead', None, user, db, [])
        assert signed.value.status_code == 409 and calls == ['sm-1']
