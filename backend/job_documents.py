"""The customer page's documents in the job's files: each signed estimate, its signed Bill of Lading, the work order and
the invoice. Nothing is copied: signed ones are read from their signature rows, the work order and invoice are built
as the customer page builds them."""
from fastapi import HTTPException

WORK_ORDER, INVOICE = 'work-order', 'invoice'
ESTIMATE_PREFIX, BILL_OF_LADING_PREFIX = 'estimate-', 'bill-of-lading-'


def _item(document_id, job, file_name, file_size, created_at):
    return {'id': document_id, 'lead_id': job.lead_id, 'job_id': job.id, 'file_name': file_name,
            'content_type': 'application/pdf', 'file_size': file_size, 'external_url': '', 'is_external_link': False,
            'external_source': 'customer_page', 'source_external_id': '', 'uploaded_by': '', 'uploaded_by_name': '',
            'created_at': created_at.isoformat() + 'Z' if created_at else '', 'document': True}


def _signed_estimates(db, job):
    from models import EstimateSignature
    return (db.query(EstimateSignature).filter(EstimateSignature.job_id == job.id, EstimateSignature.signed_at.isnot(None))
            .order_by(EstimateSignature.signed_at.desc()).all())


def _latest_bill_of_lading(db, estimate):
    """The estimate's Bill of Lading as last signed since this signing: its PDF carries every spot signed so far."""
    from models import BillOfLadingSignature
    return (db.query(BillOfLadingSignature)
            .filter(BillOfLadingSignature.estimate_signature_id == estimate.id, BillOfLadingSignature.signed_at >= estimate.signed_at)
            .order_by(BillOfLadingSignature.signed_at.desc()).first())


def _access(db, job):
    from models import PublicMoveAccess
    return db.query(PublicMoveAccess).filter_by(lead_id=job.lead_id, job_id=job.id).first()


def job_document_items(db, job):
    """The job's documents, as job file rows."""
    items = []
    estimates = _signed_estimates(db, job)
    for estimate in estimates:
        items.append(_item(ESTIMATE_PREFIX + estimate.id, job, f'Signed estimate - {estimate.signer_name or ""}'.strip(' -') + '.pdf',
                           len(estimate.pdf or b''), estimate.signed_at))
        bill = _latest_bill_of_lading(db, estimate)
        if bill:
            items.append(_item(BILL_OF_LADING_PREFIX + bill.id, job, 'Signed Bill of Lading.pdf', len(bill.pdf or b''), bill.signed_at))
    access = _access(db, job)
    if access:
        if estimates:
            items.append(_item(WORK_ORDER, job, 'Work order.pdf', 0, None))
        # As on the customer page: the invoice is there once the move has a CRM payment.
        from models import LeadPayment
        if db.query(LeadPayment.id).filter(LeadPayment.lead_id == job.lead_id, LeadPayment.source == 'crm').first():
            items.append(_item(INVOICE, job, 'Invoice.pdf', 0, None))
    return items


def job_document(db, job, document_id):
    """(pdf, file name) of one of the job's documents, or None when the id is not one."""
    from models import BillOfLadingSignature, EstimateSignature
    if document_id.startswith(ESTIMATE_PREFIX):
        record = db.query(EstimateSignature).filter_by(id=document_id[len(ESTIMATE_PREFIX):], job_id=job.id).first()
        if not record or not record.signed_at:
            raise HTTPException(404, 'Signed estimate not found')
        return record.pdf, 'estimate-' + record.id + '.pdf'
    if document_id.startswith(BILL_OF_LADING_PREFIX):
        record = db.query(BillOfLadingSignature).filter_by(id=document_id[len(BILL_OF_LADING_PREFIX):], job_id=job.id).first()
        if not record:
            raise HTTPException(404, 'Signed Bill of Lading not found')
        return record.pdf, 'bill-of-lading-' + record.id + '.pdf'
    if document_id in (WORK_ORDER, INVOICE):
        from routes.public_moves import invoice_document, work_order_document
        access = _access(db, job)
        if not access:
            raise HTTPException(404, 'This job has no customer page')
        return (work_order_document if document_id == WORK_ORDER else invoice_document)(access, db)
    return None
