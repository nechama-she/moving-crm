"""Customer activity for the work queue: what customers did on their customer pages. For now, their signatures."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import BillOfLadingSignature, Company, EstimateSignature, Lead, LeadJob, User, job_number

router = APIRouter(prefix="/api/customer-activity", tags=["Customer activity"])


@router.get("")
def list_customer_activity(days: int = Query(30, ge=1, le=365), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Estimates and Bill of Lading spots signed on customer pages, newest first. A cancelled estimate signature is no
    longer signed, so it is not listed."""
    from bill_of_lading_pdf import SIGN_SPOTS
    since = datetime.utcnow() - timedelta(days=days)
    items = []
    for model, kind in ((EstimateSignature, 'estimate'), (BillOfLadingSignature, 'bill_of_lading')):
        rows = (db.query(model, Lead, LeadJob, Company.name)
                .join(Lead, Lead.id == model.lead_id).join(LeadJob, LeadJob.id == model.job_id)
                .outerjoin(Company, Company.id == LeadJob.company_id)
                .filter(model.signed_at.isnot(None), model.signed_at >= since)
                .order_by(model.signed_at.desc()).limit(200))
        for signature, lead, job, company in rows:
            items.append({'id': signature.id, 'kind': kind, 'spot': signature.spot + 1 if kind == 'bill_of_lading' else None,
                          'spots': SIGN_SPOTS, 'lead_id': lead.id, 'client': lead.full_name or '', 'job_id': job.id,
                          'job_number': job_number(lead, job), 'company': company or '', 'signer': signature.signer_name or '',
                          'signed_at': signature.signed_at.isoformat() + 'Z'})
    items.sort(key=lambda item: item['signed_at'], reverse=True)
    return {'items': items[:200]}
