import logging
import os

from fastapi import APIRouter, HTTPException, Query, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from config import get_config
from database import get_db
from models import Lead, User, UserCompany, Company

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Leads"])

# Statuses that dispatch can see (booked and beyond)
DISPATCH_STATUSES = {"booked", "scheduled", "completed"}


def _get_user_company_ids(user: User, db: Session) -> list[str]:
    """Get company IDs the user has access to."""
    rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
    return [r[0] for r in rows]


@router.get("/leads")
def get_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default=""),
    status: str = Query(default=""),
    company_id: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company_ids = _get_user_company_ids(user, db)
    if not company_ids:
        return {"items": [], "total": 0, "has_more": False}

    query = db.query(Lead).filter(Lead.company_id.in_(company_ids))

    # Filter by specific company if requested
    if company_id and company_id in company_ids:
        query = query.filter(Lead.company_id == company_id)

    # Role-based filtering
    if user.role == "sales_rep":
        query = query.filter(Lead.assigned_to == user.id)
    elif user.role == "dispatch":
        query = query.filter(Lead.status.in_(DISPATCH_STATUSES))
    # admin sees all leads for their companies

    # Status filter
    if status:
        query = query.filter(Lead.status == status)

    # Search
    if search.strip():
        q = f"%{search.strip().lower()}%"
        query = query.filter(
            Lead.full_name.ilike(q)
            | Lead.leadgen_id.ilike(q)
            | Lead.phone.ilike(q)
            | Lead.email.ilike(q)
        )

    query = query.order_by(Lead.created_time.desc())
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    has_more = offset + limit < total

    return {
        "items": [lead.to_dict() for lead in items],
        "total": total,
        "has_more": has_more,
    }


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        # Also try by leadgen_id for backwards compatibility
        lead = db.query(Lead).filter(Lead.leadgen_id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead.to_dict()


class LeadUpdate(BaseModel):
    status: str | None = None
    priority: int | None = None
    assigned_to: str | None = None
    notes: str | None = None


@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: str,
    body: LeadUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Only admin can assign leads
    if body.assigned_to is not None and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can assign leads")

    if body.status is not None:
        lead.status = body.status
    if body.priority is not None:
        lead.priority = body.priority
    if body.assigned_to is not None:
        lead.assigned_to = body.assigned_to or None
    if body.notes is not None:
        lead.notes = body.notes

    db.commit()
    db.refresh(lead)
    return lead.to_dict()


# ---- POST /api/leads — create a new lead from Zapier / external source ----

MOVE_TYPE_MAP = {
    "out of state": "interstate",
    "within the state": "local",
    "out_of_state": "interstate",
    "in_state": "local",
    "interstate": "interstate",
    "local": "local",
}


class NewLead(BaseModel):
    full_name: str = ""
    email: str = ""
    phone_number: str = ""
    pickup_zip: str = ""
    delivery_zip: str = ""
    move_size: str = ""
    move_date: str = ""
    move_type: str = ""
    created_time: str = ""
    leadgen_id: str = ""
    smartmoving_id: str = ""
    notes: str = ""
    referral_source: str = ""
    service_type: str = ""
    source: str = "zapier"


@router.post("/leads")
def create_lead(
    body: NewLead,
    x_api_secret: str = Header(...),
    db: Session = Depends(get_db),
):
    cfg = get_config()
    secret = cfg.get("API_SECRET", os.getenv("API_SECRET", ""))
    if not secret:
        raise HTTPException(status_code=500, detail="API secret not configured")
    if x_api_secret != secret:
        raise HTTPException(status_code=401, detail="Invalid API secret")

    if not body.full_name.strip():
        raise HTTPException(status_code=400, detail="full_name is required")

    # Deduplicate by smartmoving_id
    if body.smartmoving_id.strip():
        existing = db.query(Lead).filter(Lead.smartmoving_id == body.smartmoving_id.strip()).first()
        if existing:
            return {"status": "skipped", "reason": "duplicate", "smartmoving_id": body.smartmoving_id}

    company = db.query(Company).filter(Company.name == "Gorilla Haulers").first()
    if not company:
        raise HTTPException(status_code=500, detail="Company not found")

    raw_move_type = body.move_type.lower().strip()

    lead = Lead(
        company_id=company.id,
        full_name=body.full_name.strip(),
        email=body.email.strip(),
        phone=body.phone_number.strip(),
        source=body.source or "zapier",
        leadgen_id=body.leadgen_id.strip() or None,
        smartmoving_id=body.smartmoving_id.strip() or None,
        pickup_zip=body.pickup_zip.strip(),
        delivery_zip=body.delivery_zip.strip(),
        move_size=body.move_size.strip(),
        move_date=body.move_date.strip(),
        move_type=MOVE_TYPE_MAP.get(raw_move_type, raw_move_type),
        created_time=body.created_time.strip(),
        notes=body.notes.strip() or None,
        referral_source=body.referral_source.strip() or None,
        service_type=body.service_type.strip() or None,
        status="new",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    logger.info("Created lead: %s (%s)", lead.full_name, lead.id)
    return {"status": "created", "lead_id": lead.id, "full_name": lead.full_name}
