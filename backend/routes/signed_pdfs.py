"""The staff archive of signed PDFs, shown with each job's files. It only lists and opens the copies; nothing else
reads them."""
import os

import boto3
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import SignedPdfArchive, User

router = APIRouter(prefix='/api/leads', tags=['Signed PDF archive'])

KIND_TITLES = {'estimate': 'Estimate', 'bill_of_lading': 'Bill of Lading'}


@router.get('/{lead_id}/signed-pdfs')
def list_signed_pdfs(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from routes.leads import _get_visible_lead_or_404
    lead = _get_visible_lead_or_404(lead_id, user, db)
    rows = (db.query(SignedPdfArchive).filter(SignedPdfArchive.lead_id == lead.id)
            .order_by(SignedPdfArchive.signed_at.desc()).all())
    return {'items': [{'id': row.id, 'job_id': row.job_id, 'kind': row.kind, 'title': KIND_TITLES.get(row.kind, row.kind),
                       'spot': row.spot, 'signer_name': row.signer_name, 'signed_at': row.signed_at.isoformat() + 'Z'}
                      for row in rows]}


@router.get('/{lead_id}/signed-pdfs/{archive_id}/url')
def signed_pdf_url(lead_id: str, archive_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from routes.leads import _get_visible_lead_or_404
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = db.query(SignedPdfArchive).filter_by(id=archive_id, lead_id=lead.id).first()
    if row is None:
        raise HTTPException(404, 'Signed PDF not found')
    bucket = (os.getenv('ATTACHMENTS_BUCKET') or '').strip()
    if not bucket:
        raise HTTPException(500, 'Attachment storage is not configured')
    url = boto3.client('s3').generate_presigned_url(
        'get_object', ExpiresIn=300,
        Params={'Bucket': bucket, 'Key': row.s3_key, 'ResponseContentType': 'application/pdf', 'ResponseContentDisposition': 'inline'})
    return {'url': url}
