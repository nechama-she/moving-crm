"""Editable report file set; historical snapshots retain their original files."""
from datetime import datetime
from fastapi import HTTPException
from models import LeadAttachment


def move_files(access, db, all_lead=False, include_removed=False):
    return db.query(LeadAttachment).filter(
        LeadAttachment.lead_id == access.lead_id,
        True if all_lead else ((LeadAttachment.job_id == access.job_id) | LeadAttachment.job_id.is_(None)),
        True if include_removed else LeadAttachment.report_deleted_at.is_(None),
    ).order_by(LeadAttachment.created_at, LeadAttachment.id).all()


def remove_report_file(access, attachment_id, db):
    row = db.query(LeadAttachment).filter(
        LeadAttachment.id == attachment_id, LeadAttachment.lead_id == access.lead_id,
        (LeadAttachment.job_id == access.job_id) | LeadAttachment.job_id.is_(None),
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, 'File not found on this move.')
    if row.report_deleted_at is None:
        row.report_deleted_at = datetime.utcnow()
    db.commit()
    return {'ok': True}


def file_list(rows):
    return [{'id': row.id, 'name': row.file_name, 'size': row.file_size, 'content_type': row.content_type} for row in rows]


def validate_report_media(row):
    import boto3
    from urllib.parse import urlparse
    from media_type import detected_media_type
    location = urlparse(row.external_url or '')
    try:
        if location.scheme == 's3':
            storage = boto3.client('s3')
            metadata = storage.head_object(Bucket=location.netloc, Key=location.path.lstrip('/'))
            size = metadata['ContentLength']
            stream = storage.get_object(Bucket=location.netloc, Key=location.path.lstrip('/'), Range='bytes=0-63')['Body']
            try:
                header = stream.read(64)
            finally:
                stream.close()
            declared_type = row.content_type or metadata.get('ContentType')
        else:
            content = bytes(row.file_blob or b'')
            size, header = len(content), content[:64]
            declared_type = row.content_type
    except Exception as exc:
        raise HTTPException(502, f'Could not read {row.file_name} from CRM storage. Please retry.') from exc
    if not size or not header:
        raise HTTPException(400, f'{row.file_name} has no stored file content. Upload the original file to the CRM first.')
    detected = detected_media_type(header, 'application/octet-stream')
    row.content_type = detected if detected != 'application/octet-stream' else (declared_type or 'application/octet-stream').split(';')[0].strip().lower()
    row.file_size = size


def preview_report_file(access, attachment_id, db, download=False, all_lead=False, include_removed=False):
    import base64
    import boto3
    from urllib.parse import urlparse
    row = db.query(LeadAttachment).filter(
        LeadAttachment.id == attachment_id, LeadAttachment.lead_id == access.lead_id,
        True if all_lead else ((LeadAttachment.job_id == access.job_id) | LeadAttachment.job_id.is_(None)),
        True if include_removed else LeadAttachment.report_deleted_at.is_(None),
    ).first()
    if not row:
        raise HTTPException(404, 'File not found on this move.')
    inline_types = ('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif',
                    'video/mp4', 'video/webm', 'video/quicktime', 'audio/mpeg', 'audio/mp4', 'audio/wav', 'audio/ogg', 'application/pdf')
    download = download or row.content_type not in inline_types
    location = urlparse(row.external_url or '')
    if location.scheme == 's3':
        url = boto3.client('s3').generate_presigned_url('get_object', Params={
            'Bucket': location.netloc, 'Key': location.path.lstrip('/'),
            'ResponseContentType': 'application/octet-stream' if download else row.content_type, 'ResponseContentDisposition': 'attachment' if download else 'inline'}, ExpiresIn=3600)
        return {'url': url}
    if row.file_blob:
        return {'url': 'data:' + row.content_type + ';base64,' + base64.b64encode(row.file_blob).decode('ascii')}
    return {'url': None}
