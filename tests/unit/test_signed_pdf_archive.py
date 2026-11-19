"""Every signed PDF is copied to the archive; a signature is never removed without a copy; only the staff archive page
reads the archive."""
import json
import re
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from test_public_moves import portal

ROOT = Path(__file__).resolve().parents[2]


def _signed(portal, monkeypatch, s3):
    import boto3
    import estimate_pdf
    from models import LeadJob
    mod, db, lead, access = portal
    monkeypatch.setenv('ATTACHMENTS_BUCKET', 'bucket')
    monkeypatch.setattr(boto3, 'client', lambda name: s3)
    monkeypatch.setattr(mod, '_estimate_document', lambda *args: ({'estimate': {'price': 100, 'charges': []}}, []))
    monkeypatch.setattr(estimate_pdf, 'build_estimate_pdf', lambda data, rows: json.dumps(data).encode())
    version = mod.prepare_estimate_signature(access, db)['id']
    db.get(LeadJob, access.job_id).estimate_approved_id = version
    db.commit()
    mod.sign_estimate(version, mod.SigningInput(name='Jane', consent=True, strokes=[[(.1, .2), (.3, .4)]]), access, db)
    return mod, db, access, version


def test_signing_copies_the_signed_pdf_to_the_archive(portal, monkeypatch):
    from models import EstimateSignature, SignedPdfArchive
    s3 = Mock()
    mod, db, access, version = _signed(portal, monkeypatch, s3)
    row = db.query(SignedPdfArchive).one()
    record = db.get(EstimateSignature, version)
    assert (row.kind, row.signature_id, row.signer_name, row.signed_at) == ('estimate', version, 'Jane', record.signed_at)
    s3.put_object.assert_called_once()
    assert s3.put_object.call_args.kwargs['Body'] == bytes(record.pdf)
    assert s3.put_object.call_args.kwargs['Key'] == row.s3_key


def test_a_failed_copy_does_not_undo_the_signing_and_removal_asks_before_removing_without_one(portal, monkeypatch):
    from models import EstimateSignature, SignedPdfArchive
    s3 = Mock()
    s3.put_object.side_effect = RuntimeError('S3 down')
    mod, db, access, version = _signed(portal, monkeypatch, s3)
    record = db.get(EstimateSignature, version)
    assert record.signed_at is not None and not db.query(SignedPdfArchive).count()
    signed_pdf = bytes(record.pdf)
    # S3 still down: the person is asked first, and the signature stays until they confirm.
    with pytest.raises(HTTPException) as asked:
        mod.clear_estimate_signature(version, access, db, without_copy=False)
    assert asked.value.status_code == 409 and asked.value.detail['code'] == 'no_copy'
    db.refresh(record)
    assert record.signed_at is not None and bytes(record.pdf) == signed_pdf
    # Confirmed: removed without a copy.
    mod.clear_estimate_signature(version, access, db, without_copy=True)
    db.refresh(record)
    assert record.signed_at is None and not db.query(SignedPdfArchive).count()


def test_removal_copies_the_signed_pdf_first_when_it_was_not_archived(portal, monkeypatch):
    from models import EstimateSignature, SignedPdfArchive
    s3 = Mock()
    s3.put_object.side_effect = RuntimeError('S3 down')
    mod, db, access, version = _signed(portal, monkeypatch, s3)
    signed_pdf = bytes(db.get(EstimateSignature, version).pdf)
    s3.put_object.side_effect = None
    mod.clear_estimate_signature(version, access, db, without_copy=False)
    row = db.query(SignedPdfArchive).one()
    assert s3.put_object.call_args.kwargs['Body'] == signed_pdf and row.signer_name == 'Jane'
    assert db.get(EstimateSignature, version).signed_at is None


def test_only_the_staff_archive_page_reads_the_archive():
    allowed = {'backend/models.py', 'backend/signed_pdf_archive.py', 'backend/routes/signed_pdfs.py', 'backend/migrate.py'}
    users = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'backend').rglob('*.py')
             if '.venv' not in path.parts and re.search(r'SignedPdfArchive|signed_pdf_archive\b(?!\.py)', path.read_text(encoding='utf-8'))
             and path.relative_to(ROOT).as_posix() not in allowed}
    # The customer page code only writes copies, through signed_pdf_archive.archive.
    assert users == {'backend/routes/public_moves.py'}
    source = (ROOT / 'backend/routes/public_moves.py').read_text(encoding='utf-8')
    assert 'SignedPdfArchive' not in source
    assert set(re.findall(r'from signed_pdf_archive import (\w+)', source)) == {'archive'}
