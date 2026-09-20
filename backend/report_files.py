"""Editable report file set; historical snapshots retain their original files."""
from datetime import datetime
from fastapi import HTTPException
from models import LeadAttachment


def move_files(access, db):
    return db.query(LeadAttachment).filter(
        LeadAttachment.lead_id == access.lead_id,
        (LeadAttachment.job_id == access.job_id) | LeadAttachment.job_id.is_(None),
        LeadAttachment.report_deleted_at.is_(None),
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
    return [{'id': row.id, 'name': row.file_name, 'size': row.file_size} for row in rows]
