"""The customer page's documents in the job files, read from where they are saved: nothing is copied."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def db():
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from models import Base, BillOfLadingSignature, EstimateSignature, Lead, LeadAttachment, LeadJob
    import estimate_approval
    hook = estimate_approval._clear_changed_approvals
    hooked = event.contains(Session, 'before_flush', hook)
    if hooked:
        event.remove(Session, 'before_flush', hook)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    signed_at = datetime(2026, 11, 1, 12)
    with Session(engine) as session:
        session.add(Lead(id='lead', full_name='Pat Mover'))
        session.flush()
        session.add(LeadJob(id='job', lead_id='lead', job_order=1))
        session.flush()
        session.add_all([
            EstimateSignature(id='signed', lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF-signed', signer_name='Pat Mover', signed_at=signed_at),
            EstimateSignature(id='unsigned', lead_id='lead', job_id='job', snapshot='{}', pdf=b'%PDF-draft')])
        session.flush()
        session.add_all([
            BillOfLadingSignature(id='spot1', lead_id='lead', job_id='job', estimate_signature_id='signed', content_hash='h', spot=0,
                                  pdf=b'%PDF-one', signer_name='Pat', signature='{}', signed_at=signed_at + timedelta(minutes=1)),
            BillOfLadingSignature(id='spot2', lead_id='lead', job_id='job', estimate_signature_id='signed', content_hash='h', spot=1,
                                  pdf=b'%PDF-both', signer_name='Pat', signature='{}', signed_at=signed_at + timedelta(minutes=2))])
        session.commit()
        yield session
    engine.dispose()
    if hooked:
        event.listen(Session, 'before_flush', hook)


def test_signed_estimate_and_its_latest_bill_of_lading_are_listed_and_opened(db):
    from job_documents import job_document, job_document_items
    from models import LeadAttachment, LeadJob
    job = db.get(LeadJob, 'job')
    items = job_document_items(db, job)
    assert [item['id'] for item in items] == ['estimate-signed', 'bill-of-lading-spot2']
    assert all(item['document'] for item in items)
    assert job_document(db, job, 'estimate-signed')[0] == b'%PDF-signed'
    assert job_document(db, job, 'bill-of-lading-spot2')[0] == b'%PDF-both'
    # Nothing is copied into the job's files, and an uploaded file's id is not a document.
    assert db.query(LeadAttachment).count() == 0
    assert job_document(db, job, 'some-upload-id') is None


def test_an_unsigned_estimate_is_not_opened(db):
    from fastapi import HTTPException
    from job_documents import job_document
    from models import LeadJob
    with pytest.raises(HTTPException):
        job_document(db, db.get(LeadJob, 'job'), 'estimate-unsigned')


def test_no_customer_page_no_work_order_or_invoice(db):
    from job_documents import job_document_items
    from models import LeadJob
    job = db.get(LeadJob, 'job')
    job.price = 1000
    assert {'work-order', 'invoice'}.isdisjoint(item['id'] for item in job_document_items(db, job))
