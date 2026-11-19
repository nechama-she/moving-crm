"""A job has one signed estimate at a time: a page that missed the signing cannot approve or sign another copy."""
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_a_second_copy_is_refused_until_the_signature_is_removed():
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, EstimateSignature, Lead, LeadJob
    from routes.public_moves import _refuse_a_second_signature
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Lead(id='lead', full_name='Pat'))
        db.flush()
        db.add(LeadJob(id='job', lead_id='lead', job_order=1))
        db.flush()
        db.add_all([EstimateSignature(id='signed', lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF', signed_at=datetime(2026, 11, 1)),
                    EstimateSignature(id='stale-copy', lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF')])
        db.commit()
        access = SimpleNamespace(lead_id='lead', job_id='job')
        with pytest.raises(HTTPException) as refused:
            _refuse_a_second_signature(db.get(EstimateSignature, 'stale-copy'), access, db)
        assert refused.value.status_code == 409 and 'Re-sign' in refused.value.detail
        # After Re-sign removes the signature, another copy can be approved and signed.
        db.get(EstimateSignature, 'signed').signed_at = None
        db.commit()
        _refuse_a_second_signature(db.get(EstimateSignature, 'stale-copy'), access, db)
    engine.dispose()
