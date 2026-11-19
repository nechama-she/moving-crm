"""Every signed PDF, copied to S3 for the record. Only signing code writes here and only the staff archive page reads
it: the customer page never uses these copies."""
import os

import boto3

from models import SignedPdfArchive


def archive(db, kind, record, spot=None):
    """Copies this signing's PDF to S3 and records it, once per signing. Raises when the copy cannot be saved."""
    if db.query(SignedPdfArchive.id).filter_by(kind=kind, signature_id=record.id, signed_at=record.signed_at).first():
        return
    bucket = (os.getenv('ATTACHMENTS_BUCKET') or '').strip()
    if not bucket:
        raise RuntimeError('ATTACHMENTS_BUCKET is not configured')
    key = (f"signed-pdfs/leads/{record.lead_id}/jobs/{record.job_id}/{kind}/"
           f"{record.id}-{record.signed_at.strftime('%Y%m%dT%H%M%S')}.pdf")
    boto3.client('s3').put_object(Bucket=bucket, Key=key, Body=bytes(record.pdf), ContentType='application/pdf',
                                  ServerSideEncryption='AES256')
    db.add(SignedPdfArchive(lead_id=record.lead_id, job_id=record.job_id, kind=kind, signature_id=record.id, spot=spot,
                            signer_name=record.signer_name, signed_at=record.signed_at, s3_key=key))
