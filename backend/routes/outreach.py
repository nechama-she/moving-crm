import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Company, Lead, OutreachEvent, User, UserCompany

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Outreach"])


def _get_user_company_ids(user: User, db: Session) -> list[str]:
    if user.role == "admin":
        return [row[0] for row in db.query(Company.id).all()]
    rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
    return [r[0] for r in rows]


@router.get("/outreach-events")
def get_outreach_events(
    limit: int = Query(default=100, ge=1, le=500),
    outreach_type: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company_ids = _get_user_company_ids(user, db)
    if not company_ids:
        return {"items": []}

    try:
        query = db.query(OutreachEvent).filter(OutreachEvent.company_id.in_(company_ids))
        if outreach_type.strip():
            query = query.filter(OutreachEvent.outreach_type == outreach_type.strip())

        rows = query.order_by(OutreachEvent.created_at.desc()).limit(limit).all()
        lead_ids = [row.lead_id for row in rows if row.lead_id]
        leads = {}
        if lead_ids:
            lead_rows = db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
            leads = {lead.id: lead for lead in lead_rows}

        items = []
        for row in rows:
            item = row.to_dict()
            lead = leads.get(row.lead_id)
            item["lead_name"] = lead.full_name if lead else ""
            item["lead_url"] = f"/leads/{row.lead_id}" if row.lead_id else ""
            items.append(item)

        return {"items": items}
    except Exception as exc:
        logger.warning("Non-fatal outreach events read failure: %s", exc)
        return {"items": []}
