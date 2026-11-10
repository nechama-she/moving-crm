"""Work queue customer activity: estimates and Bill of Lading spots signed on customer pages, newest first."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


def test_signatures_newest_first_without_unsigned_or_old_ones():
    from models import Base, BillOfLadingSignature, Company, EstimateSignature, Lead, LeadJob
    from routes.customer_activity import list_customer_activity
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    now = datetime.utcnow()
    with Session(engine) as db:
        db.add(Company(id='gorilla', name='Gorilla Haulers'))
        db.add(Lead(id='lead', full_name='Jane Doe', number='48213075526'))
        db.flush()
        db.add(LeadJob(id='job', lead_id='lead', job_order=1, company_id='gorilla'))
        db.flush()
        db.add_all([
            EstimateSignature(id='signed', lead_id='lead', job_id='job', snapshot='{}', pdf=b'', signer_name='Jane', signed_at=now - timedelta(hours=2)),
            EstimateSignature(id='cancelled', lead_id='lead', job_id='job', snapshot='{}', pdf=b''),
            EstimateSignature(id='old', lead_id='lead', job_id='job', snapshot='{}', pdf=b'', signer_name='Jane', signed_at=now - timedelta(days=40)),
        ])
        db.flush()
        db.add(BillOfLadingSignature(id='bol', lead_id='lead', job_id='job', estimate_signature_id='signed', content_hash='x', spot=1,
                                     pdf=b'', signer_name='Jane D', signature='{}', signed_at=now - timedelta(hours=1)))
        db.commit()
        items = list_customer_activity(30, SimpleNamespace(role='admin'), db)['items']
    assert [(row['id'], row['kind'], row['spot']) for row in items] == [('bol', 'bill_of_lading', 2), ('signed', 'estimate', None)]
    assert {row['job_number'] for row in items} == {'48213075526-1'}
    assert (items[0]['client'], items[0]['company'], items[0]['signer']) == ('Jane Doe', 'Gorilla Haulers', 'Jane D')
    engine.dispose()
