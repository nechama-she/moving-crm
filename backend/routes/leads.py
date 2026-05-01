import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Depends, Header
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from config import get_config
from database import get_db
from models import Lead, User, UserCompany, Company, OutreachEvent, AdminUnavailability, AdminUnavailabilityRep, RepAvailabilityWindow, AutoAssignEvent

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Leads"])

# Statuses that dispatch can see (booked and beyond)
DISPATCH_STATUSES = {"booked", "scheduled", "completed"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin_unavailable_now(admin_user_id: str, db: Session, now: datetime | None = None) -> bool:
    ts = now or _utcnow()
    return (
        db.query(AdminUnavailability)
        .filter(
            AdminUnavailability.admin_user_id == admin_user_id,
            AdminUnavailability.start_at <= ts,
            AdminUnavailability.end_at > ts,
        )
        .first()
        is not None
    )


def _any_admin_available_now(db: Session, now: datetime | None = None) -> bool:
    ts = now or _utcnow()
    admins = db.query(User).filter(User.role == "admin").all()
    if not admins:
        return False
    for admin in admins:
        if not _is_admin_unavailable_now(admin.id, db, ts):
            return True
    return False


def _active_available_rep_ids(db: Session, now: datetime | None = None) -> set[str]:
    ts = now or _utcnow()
    window_ids = [
        row[0]
        for row in (
            db.query(AdminUnavailability.id)
            .filter(AdminUnavailability.start_at <= ts, AdminUnavailability.end_at > ts)
            .all()
        )
    ]
    if not window_ids:
        return set()
    rep_rows = db.query(AdminUnavailabilityRep.rep_user_id).filter(AdminUnavailabilityRep.window_id.in_(window_ids)).all()
    return {r[0] for r in rep_rows if r[0]}


def _filter_by_rep_availability(rep_ids: list[str], db: Session, now: datetime | None = None) -> set[str]:
    if not rep_ids:
        return set()

    ts = now or _utcnow()
    configured_rows = (
        db.query(RepAvailabilityWindow.rep_user_id)
        .filter(RepAvailabilityWindow.rep_user_id.in_(rep_ids))
        .distinct()
        .all()
    )
    configured_rep_ids = {r[0] for r in configured_rows if r[0]}

    active_rows = (
        db.query(RepAvailabilityWindow.rep_user_id)
        .filter(
            RepAvailabilityWindow.rep_user_id.in_(rep_ids),
            RepAvailabilityWindow.start_at <= ts,
            RepAvailabilityWindow.end_at > ts,
        )
        .distinct()
        .all()
    )
    active_rep_ids = {r[0] for r in active_rows if r[0]}

    # If a rep has no configured windows, keep backward-compatible default: available.
    return {rid for rid in rep_ids if (rid not in configured_rep_ids or rid in active_rep_ids)}


def _active_reps_for_company(
    company_id: str,
    db: Session,
    allowed_rep_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[User]:
    rep_rows = (
        db.query(User)
        .join(UserCompany, UserCompany.user_id == User.id)
        .filter(User.role == "sales_rep", UserCompany.company_id == company_id)
        .order_by(User.name.asc())
        .all()
    )
    if allowed_rep_ids is not None:
        rep_rows = [u for u in rep_rows if u.id in allowed_rep_ids]

    active_ids = _filter_by_rep_availability([r.id for r in rep_rows], db, now=now)
    return [u for u in rep_rows if u.id in active_ids]


def _pick_round_robin_rep_for_company(
    company_id: str,
    db: Session,
    allowed_rep_ids: set[str] | None = None,
    now: datetime | None = None,
) -> User | None:
    active_reps = _active_reps_for_company(company_id, db, allowed_rep_ids=allowed_rep_ids, now=now)
    if not active_reps:
        return None

    rep_ids = [r.id for r in active_reps]
    last_event = (
        db.query(AutoAssignEvent)
        .filter(
            AutoAssignEvent.company_id == company_id,
            AutoAssignEvent.assignment_mode == "auto",
            AutoAssignEvent.assigned_to.in_(rep_ids),
        )
        .order_by(AutoAssignEvent.created_at.desc(), AutoAssignEvent.id.desc())
        .first()
    )
    if not last_event or not last_event.assigned_to:
        return active_reps[0]

    id_to_index = {rep.id: idx for idx, rep in enumerate(active_reps)}
    if last_event.assigned_to not in id_to_index:
        return active_reps[0]

    next_idx = (id_to_index[last_event.assigned_to] + 1) % len(active_reps)
    return active_reps[next_idx]


def _pick_available_rep_for_company(company_id: str, db: Session, allowed_rep_ids: set[str] | None = None) -> User | None:
    rep_rows = (
        db.query(User)
        .join(UserCompany, UserCompany.user_id == User.id)
        .filter(User.role == "sales_rep", UserCompany.company_id == company_id)
        .order_by(User.name.asc())
        .all()
    )
    if allowed_rep_ids is not None:
        rep_rows = [u for u in rep_rows if u.id in allowed_rep_ids]

    rep_rows = [u for u in rep_rows if u.id in _filter_by_rep_availability([r.id for r in rep_rows], db)]
    if not rep_rows:
        return None

    rep_ids = [u.id for u in rep_rows]
    counts = dict(
        db.query(Lead.assigned_to, func.count(Lead.id))
        .filter(Lead.company_id == company_id, Lead.assigned_to.in_(rep_ids))
        .group_by(Lead.assigned_to)
        .all()
    )

    # Pick least-loaded rep for this company; ties resolved by alphabetical name.
    return min(rep_rows, key=lambda u: (counts.get(u.id, 0), u.name.lower()))


def _send_assignment_webhook_todo(lead: Lead, rep: User | None):
    if not rep:
        return
    # TODO: Call external assignment webhook/API here to mirror CRM assignment downstream.
    logger.info("TODO assignment webhook: lead=%s rep=%s(%s)", lead.id, rep.id, rep.name)


def _get_user_company_ids(user: User, db: Session) -> list[str]:
    """Get company IDs the user has access to."""
    if user.role == "admin":
        return [row[0] for row in db.query(Company.id).all()]
    rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
    return [r[0] for r in rows]


def _lookup_sender_id(lead: Lead) -> str | None:
    """Try to find a matching sender_id from DynamoDB sender_info table."""
    from boto3.dynamodb.conditions import Attr
    from db import sender_info_table

    filters = []
    if lead.phone:
        filters.append(Attr("phone").eq(lead.phone))
    if lead.email:
        filters.append(Attr("email").eq(lead.email))
    if lead.full_name:
        filters.append(Attr("name").eq(lead.full_name))

    if not filters:
        return None

    try:
        combined = filters[0]
        for f in filters[1:]:
            combined = combined & f
        resp = sender_info_table.scan(FilterExpression=combined)
        items = resp.get("Items", [])
        if items:
            return items[0].get("sender_id")
    except Exception as e:
        logger.warning("sender_info lookup failed for lead %s: %s", lead.id, e)
    return None


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

    # If facebook_user_id is missing, try to find it from sender_info
    if not lead.facebook_user_id:
        sender_id = _lookup_sender_id(lead)
        if sender_id:
            lead.facebook_user_id = sender_id
            db.commit()
            logger.info("Matched sender_id %s for lead %s", sender_id, lead.id)

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
    facebook_user_id: str = ""
    notes: str = ""
    referral_source: str = ""
    service_type: str = ""
    company_name: str
    source: str


SMS_TEMPLATE = """Hi {first_name},
Thank you for reaching out to {company_name} regarding your upcoming move.

To provide an accurate quote, we can schedule a virtual in-home estimate, complete the estimate over the phone with one of our estimators, or schedule a free in-home estimate.

You can also submit your inventory here for a quick estimate:
https://portal.smartmoving.com/home/inventory/{smartmoving_id}/welcome

Please let us know the best time to discuss your move.
You can also call us anytime at {company_phone}.

{company_name}"""


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

    company = db.query(Company).filter(Company.name == body.company_name.strip()).first()
    if not company:
        raise HTTPException(status_code=400, detail=f"Company '{body.company_name}' not found")

    assigned_to_user_id = None
    assignment_mode = "manual"
    assignment_reason = "admin_available"

    # Auto-assign only while all admins are unavailable.
    if not _any_admin_available_now(db):
        available_rep_ids = _active_available_rep_ids(db)
        rep = _pick_round_robin_rep_for_company(company.id, db, available_rep_ids)
        if rep:
            assigned_to_user_id = rep.id
            assignment_mode = "auto"
            assignment_reason = "all_admins_unavailable_round_robin"
        else:
            assignment_mode = "queued"
            assignment_reason = "all_admins_unavailable_no_available_rep"

    raw_move_type = body.move_type.lower().strip()

    lead = Lead(
        company_id=company.id,
        assigned_to=assigned_to_user_id,
        full_name=body.full_name.strip(),
        email=body.email.strip(),
        phone=body.phone_number.strip(),
        source=body.source or "zapier",
        leadgen_id=body.leadgen_id.strip() or None,
        smartmoving_id=body.smartmoving_id.strip() or None,
        facebook_user_id=body.facebook_user_id.strip() or None,
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
    if assigned_to_user_id:
        logger.info("Auto-assigned lead %s to rep %s (%s)", lead.id, assigned_to_user_id, assignment_reason)
        assigned_rep = db.query(User).filter(User.id == assigned_to_user_id).first()
        _send_assignment_webhook_todo(lead, assigned_rep)

    # Send welcome SMS if phone and smartmoving_id are present
    sms_result = None
    if lead.phone and lead.smartmoving_id:
        from libs.aircall import send_sms, find_number_id
        first_name = lead.full_name.split()[0] if lead.full_name.strip() else ""
        message = SMS_TEMPLATE.format(
            first_name=first_name,
            company_name=company.name,
            smartmoving_id=lead.smartmoving_id,
            company_phone=company.phone or "",
        )

        # Resolve Aircall number_id: use cached value or look up and store
        nid = company.aircall_number_id
        if not nid and company.phone:
            nid = find_number_id(company.phone)
            if nid:
                company.aircall_number_id = nid
                db.commit()
                logger.info("Stored aircall_number_id=%s for company %s", nid, company.name)

        sms_result = send_sms(to=lead.phone, text=message, number_id=nid)
        logger.info("Welcome SMS for lead %s: %s", lead.id, sms_result)

    try:
        assign_event = AutoAssignEvent(
            lead_id=lead.id,
            company_id=company.id,
            assigned_to=lead.assigned_to,
            assignment_mode=assignment_mode,
            assignment_reason=assignment_reason,
            note=(
                "Auto assigned while admins unavailable"
                if assignment_mode == "auto"
                else "Queued because no active rep slot" if assignment_mode == "queued" else "Admins available; no auto assignment"
            ),
        )
        db.add(assign_event)

        outreach_event = OutreachEvent(
            lead_id=lead.id,
            company_id=company.id,
            smartmoving_id=lead.smartmoving_id or "",
            note_id="",
            outreach_type="new_lead",
            job_id=lead.smartmoving_id or "",
            qualified=bool(lead.phone and lead.smartmoving_id),
            qualification_reason="ok" if lead.phone and lead.smartmoving_id else "missing_phone_or_job_id",
            message=message if lead.phone and lead.smartmoving_id else "",
            messenger=False,
            aircall=bool(lead.phone),
            dry_run=False,
        )
        db.add(outreach_event)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Non-fatal outreach event write failure for lead %s: %s", lead.id, exc)

    return {
        "status": "created",
        "lead_id": lead.id,
        "full_name": lead.full_name,
        "sms": sms_result,
        "assigned_to": lead.assigned_to or "",
        "assignment_mode": assignment_mode,
        "assignment_reason": assignment_reason,
    }
