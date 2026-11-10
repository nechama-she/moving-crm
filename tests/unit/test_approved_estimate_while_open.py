"""A rep approves an estimate while the customer has their own copy open: the page learns whether that copy says the same,
so it keeps it on screen and signs the approved one."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_approved_copy_says_whether_the_open_copy_matches():
    from models import Base, EstimateSignature, Lead, LeadJob
    from routes.public_moves import EstimateViewing, prepare_estimate_signature
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)

    def snapshot(price):
        return json.dumps({'data': {'estimate': {'price': price}}, 'rows': [{'name': 'Sofa', 'amount': 1}]})
    with Session(engine) as db:
        db.add(Lead(id='lead', full_name='Jane Doe', number='48213075526'))
        db.flush()
        db.add(LeadJob(id='job', lead_id='lead', job_order=1, estimate_approved_id='approved'))
        db.flush()
        db.add_all([EstimateSignature(id='approved', lead_id='lead', job_id='job', snapshot=snapshot(1000), pdf=b''),
                    EstimateSignature(id='open', lead_id='lead', job_id='job', snapshot=snapshot(1000), pdf=b''),
                    EstimateSignature(id='older', lead_id='lead', job_id='job', snapshot=snapshot(900), pdf=b'')])
        db.commit()
        access = SimpleNamespace(job_id='job', lead_id='lead')
        prepare = lambda viewing=None: prepare_estimate_signature(access, db, EstimateViewing(viewing=viewing) if viewing else None)
        assert prepare('open') == {'id': 'approved', 'signed': False, 'approved': True, 'same': True}
        assert prepare('older')['same'] is False
        assert prepare('approved')['same'] is False
        assert prepare() == {'id': 'approved', 'signed': False, 'approved': True, 'same': False}
    engine.dispose()
