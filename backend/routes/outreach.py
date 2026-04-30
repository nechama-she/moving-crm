import logging
from datetime import datetime

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


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@router.get("/outreach-filters")
def get_outreach_filters(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company_ids = _get_user_company_ids(user, db)
    if not company_ids:
        return {"companies": [], "sales_reps": []}

    company_rows = db.query(Company).filter(Company.id.in_(company_ids)).order_by(Company.name.asc()).all()
    companies = [{"id": c.id, "name": c.name or ""} for c in company_rows]

    rep_rows = (
        db.query(User)
        .join(UserCompany, UserCompany.user_id == User.id)
        .filter(User.role == "sales_rep", UserCompany.company_id.in_(company_ids))
        .order_by(User.name.asc())
        .all()
    )
    seen = set()
    reps = []
    for rep in rep_rows:
        if rep.id in seen:
            continue
        seen.add(rep.id)
        reps.append({"id": rep.id, "name": rep.name or "", "email": rep.email or ""})

    return {"companies": companies, "sales_reps": reps}


@router.get("/outreach-events")
def get_outreach_events(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    outreach_type: str = Query(default=""),
    company_id: str = Query(default=""),
    rep_user_id: str = Query(default=""),
    start_at: str = Query(default=""),
    end_at: str = Query(default=""),
    sort_dir: str = Query(default="desc"),
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
        if company_id.strip() and company_id in company_ids:
            query = query.filter(OutreachEvent.company_id == company_id.strip())

        parsed_start = None
        parsed_end = None
        if start_at.strip():
            try:
                parsed_start = _parse_iso_datetime(start_at.strip())
            except Exception:
                parsed_start = None
        if end_at.strip():
            try:
                parsed_end = _parse_iso_datetime(end_at.strip())
            except Exception:
                parsed_end = None
        if parsed_start is not None:
            query = query.filter(OutreachEvent.created_at >= parsed_start)
        if parsed_end is not None:
            query = query.filter(OutreachEvent.created_at <= parsed_end)

        all_rows = query.all()

        reverse = sort_dir.strip().lower() != "asc"
        all_rows.sort(key=lambda r: r.created_at or datetime.min, reverse=reverse)

        lead_ids = [row.lead_id for row in all_rows if row.lead_id]
        leads = {}
        if lead_ids:
            lead_rows = db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
            leads = {lead.id: lead for lead in lead_rows}

        if rep_user_id.strip():
            all_rows = [row for row in all_rows if (leads.get(row.lead_id).assigned_to if leads.get(row.lead_id) else "") == rep_user_id.strip()]

        total = len(all_rows)
        rows = all_rows[offset:offset + limit]

        company_map = {c.id: c.name or "" for c in db.query(Company).filter(Company.id.in_(company_ids)).all()}
        rep_ids = list({lead.assigned_to for lead in leads.values() if lead and lead.assigned_to})
        rep_map = {}
        if rep_ids:
            rep_map = {u.id: u.name or "" for u in db.query(User).filter(User.id.in_(rep_ids)).all()}

        items = []
        for row in rows:
            item = row.to_dict()
            lead = leads.get(row.lead_id)
            item["lead_name"] = lead.full_name if lead else ""
            item["lead_url"] = f"/leads/{row.lead_id}" if row.lead_id else ""
            item["company_name"] = company_map.get(row.company_id, "")
            item["sales_rep_id"] = lead.assigned_to if lead and lead.assigned_to else ""
            item["sales_rep_name"] = rep_map.get(lead.assigned_to, "") if lead and lead.assigned_to else ""
            items.append(item)

        return {"items": items, "total": total, "has_more": offset + limit < total}
    except Exception as exc:
        logger.warning("Non-fatal outreach events read failure: %s", exc)
        return {"items": [], "total": 0, "has_more": False}
