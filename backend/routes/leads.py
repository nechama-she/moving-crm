import json
import logging
import os
from datetime import datetime, date, timedelta, timezone

import boto3

from fastapi import APIRouter, HTTPException, Query, Depends, Header, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, cast
from sqlalchemy.orm import Session

from auth import get_current_user
from config import get_config
from database import get_db
from libs.common.phone import normalize_digits
from libs.smartmoving.client import update_opportunity_salesperson
from models import Lead, User, UserCompany, Company, OutreachEvent, AdminUnavailability, AdminUnavailabilityRep, RepAvailabilityWindow, AutoAssignEvent, LeadAttachment
from routes.templates import get_company_template

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Leads"])

# Statuses that dispatch can see (booked and beyond)
DISPATCH_STATUSES = {"booked", "scheduled", "completed"}


def _default_sync_result(error: str = "not_attempted") -> dict:
    return {"ok": False, "status": "n/a", "body": "(empty)", "error": error}


def _assignment_note(mode: str, sync_result: dict | None = None) -> str:
    result = sync_result or _default_sync_result()
    if mode == "auto":
        return (
            "Auto assigned while admins unavailable; "
            f"SmartMoving sync ok (status={result.get('status', 'n/a')} body={result.get('body', '(empty)')})"
        )
    if mode == "queued":
        return "Queued because no active rep slot"
    if mode == "error":
        return (
            "Failed to assign lead; smartmoving sync failed "
            f"(status={result.get('status', 'n/a')} error={result.get('error', 'unknown')} body={result.get('body', '(empty)')})"
        )
    return "Admins available; no auto assignment"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_phone(raw: str | None) -> str:
    """Strip everything except digits, then drop leading country code '1' if 11 digits."""
    digits = normalize_digits(raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _parse_booked_move_date(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return None


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


LEAD_DUPLICATE_DELAY_HOURS = 8


def _enqueue_lead_for_duplication(lead_id: str, target_company_name: str, target_referral_source: str) -> None:
    """Schedule a one-time EventBridge Scheduler invocation of the lead-duplicate Lambda.

    Uses EventBridge Scheduler (not SQS) because SQS DelaySeconds is capped at 15 minutes.
    The schedule auto-deletes after firing (ActionAfterCompletion=DELETE).
    """
    function_arn = os.getenv("LEAD_DUPLICATE_FUNCTION_ARN", "")
    role_arn = os.getenv("LEAD_DUPLICATE_SCHEDULER_ROLE_ARN", "")
    if not function_arn or not role_arn:
        logger.warning(
            "LEAD_DUPLICATE_FUNCTION_ARN or LEAD_DUPLICATE_SCHEDULER_ROLE_ARN not set; "
            "skipping schedule for lead %s",
            lead_id,
        )
        return

    from datetime import timedelta

    fire_at = _utcnow() + timedelta(hours=LEAD_DUPLICATE_DELAY_HOURS)
    # Scheduler expects naive UTC ISO8601 (no offset, no microseconds).
    schedule_at = fire_at.replace(microsecond=0, tzinfo=None).isoformat()

    # Schedule name must be unique and <=64 chars, [0-9A-Za-z_.-]
    short_id = lead_id.replace("-", "")[:24]
    epoch = int(fire_at.timestamp())
    schedule_name = f"lead-dup-{short_id}-{epoch}"

    payload = {
        "lead_id": lead_id,
        "target_company_name": target_company_name,
        "target_referral_source": target_referral_source,
    }

    try:
        scheduler = boto3.client("scheduler", region_name=os.getenv("AWS_REGION_NAME", "us-east-1"))
        scheduler.create_schedule(
            Name=schedule_name,
            ScheduleExpression=f"at({schedule_at})",
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            Target={
                "Arn": function_arn,
                "RoleArn": role_arn,
                "Input": json.dumps(payload),
                "RetryPolicy": {
                    "MaximumRetryAttempts": 0,
                    "MaximumEventAgeInSeconds": 3600,
                },
            },
        )
        logger.info(
            "Scheduled lead %s for duplication to %s at %sZ (schedule=%s)",
            lead_id, target_company_name, schedule_at, schedule_name,
        )
    except Exception as exc:
        logger.warning("Failed to schedule lead %s for duplication: %s", lead_id, exc)


def _send_assignment_webhook_todo(lead: Lead, rep: User | None):
    if not rep:
        return
    # TODO: Call external assignment webhook/API here to mirror CRM assignment downstream.
    logger.info("TODO assignment webhook: lead=%s rep=%s(%s)", lead.id, rep.id, rep.name)


def _sync_assignment_to_smartmoving(lead: Lead, rep: User | None) -> dict:
    if not rep:
        return _default_sync_result("no_rep")
    if not lead.smartmoving_id:
        return _default_sync_result("lead_missing_smartmoving_id")
    if not rep.smartmoving_rep_id:
        return _default_sync_result("rep_missing_smartmoving_rep_id")

    result = update_opportunity_salesperson(lead.smartmoving_id, rep.smartmoving_rep_id)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "unknown"),
            "status": result.get("status", "n/a"),
            "body": result.get("body", "(empty)"),
        }
    return {"ok": True, "status": result.get("status", "n/a"), "body": result.get("body", "(empty)")}


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


@router.get("/dispatch-calendar")
def get_dispatch_calendar(
    company_id: str = Query(default=""),
    move_month: str = Query(default=""),  # YYYY-MM
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "dispatch"):
        raise HTTPException(status_code=403, detail="Dispatch access required")

    if not move_month:
        raise HTTPException(status_code=400, detail="move_month is required")

    try:
        year_str, month_str = move_month.split("-")
        year = int(year_str)
        month = int(month_str)
        if month < 1 or month > 12:
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="move_month must be YYYY-MM")

    month_start = date(year, month, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    allowed_company_ids = _get_user_company_ids(user, db)
    if not allowed_company_ids:
        return {"items": []}

    target_company_ids = allowed_company_ids
    if company_id:
        if company_id not in allowed_company_ids:
            raise HTTPException(status_code=403, detail="Not allowed for this company")
        target_company_ids = [company_id]

    # Some legacy/imported leads only have move_date set. Use booked_move_date first,
    # then fallback to parsed move_date so dispatch can still see those jobs.
    rows = (
        db.query(Lead)
        .filter(Lead.company_id.in_(target_company_ids))
        .order_by(Lead.created_at.asc())
        .all()
    )

    filtered: list[tuple[Lead, date]] = []
    for row in rows:
        effective_date = row.booked_move_date or _parse_booked_move_date(row.move_date)
        if not effective_date:
            continue
        if month_start <= effective_date < next_month:
            filtered.append((row, effective_date))

    filtered.sort(key=lambda item: (item[1], item[0].created_at or datetime.min))

    company_name_by_id = {
        c.id: c.name
        for c in db.query(Company).filter(Company.id.in_(target_company_ids)).all()
    }

    return {
        "items": [
            {
                "id": row.id,
                "company_id": row.company_id,
                "company_name": company_name_by_id.get(row.company_id, ""),
                "full_name": row.full_name or "",
                "move_date": row.move_date or "",
                "booked_move_date": effective_date.isoformat(),
                "pickup_zip": row.pickup_zip or "",
                "delivery_zip": row.delivery_zip or "",
                "status": row.status or "",
            }
            for row, effective_date in filtered
        ]
    }


@router.get("/leads")
def get_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default=""),
    status: str = Query(default=""),
    company_id: str = Query(default=""),
    assigned_to: str = Query(default=""),
    sort_by: str = Query(default="created_time"),
    sort_dir: str = Query(default="desc"),
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

    # Assigned-to filter (admin/dispatch only — sales_rep is already forced above)
    if assigned_to and user.role != "sales_rep":
        if assigned_to == "__unassigned__":
            query = query.filter(Lead.assigned_to == None)  # noqa: E711
        else:
            query = query.filter(Lead.assigned_to == assigned_to)

    # Search
    if search.strip():
        q = f"%{search.strip().lower()}%"
        query = query.filter(
            Lead.full_name.ilike(q)
            | Lead.leadgen_id.ilike(q)
            | Lead.phone.ilike(q)
            | Lead.email.ilike(q)
        )

    SORTABLE = {
        "created_time": Lead.created_at,
        "full_name": Lead.full_name,
        "status": Lead.status,
        "move_size": Lead.move_size,
        "pickup_zip": Lead.pickup_zip,
        "delivery_zip": Lead.delivery_zip,
        "company_name": Company.name,
    }
    if sort_by == "company_name":
        query = query.join(Company, Lead.company_id == Company.id)
    sort_col = SORTABLE.get(sort_by, Lead.created_at)
    order = sort_col.asc() if sort_dir == "asc" else sort_col.desc()
    query = query.order_by(order)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    has_more = offset + limit < total

    return {
        "items": [lead.to_dict() for lead in items],
        "total": total,
        "has_more": has_more,
    }


@router.get("/leads/by-leadgen/{leadgen_id}")
def get_lead_by_leadgen(leadgen_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.leadgen_id == leadgen_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead.to_dict()


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


MAX_ATTACHMENT_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


def _get_visible_lead_or_404(lead_id: str, user: User, db: Session) -> Lead:
    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        lead = db.query(Lead).filter(Lead.leadgen_id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/leads/{lead_id}/attachments")
def list_lead_attachments(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    rows = (
        db.query(LeadAttachment, User)
        .outerjoin(User, LeadAttachment.uploaded_by == User.id)
        .filter(LeadAttachment.lead_id == lead.id)
        .order_by(LeadAttachment.created_at.desc())
        .all()
    )
    items = []
    for attachment, uploader in rows:
        item = attachment.to_dict()
        item["uploaded_by_name"] = uploader.name if uploader else ""
        items.append(item)
    return {"items": items}


@router.post("/leads/{lead_id}/attachments")
def upload_lead_attachment(
    lead_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_visible_lead_or_404(lead_id, user, db)

    file_name = (file.filename or "").strip()
    if not file_name:
        raise HTTPException(status_code=400, detail="File name is required")

    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(payload) > MAX_ATTACHMENT_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 15 MB)")

    row = LeadAttachment(
        lead_id=lead.id,
        file_name=file_name,
        content_type=(file.content_type or "application/octet-stream"),
        file_size=len(payload),
        file_blob=payload,
        uploaded_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.get("/leads/{lead_id}/attachments/{attachment_id}/download")
def download_lead_attachment(
    lead_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    safe_name = (row.file_name or "attachment").replace('"', "")
    headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
    return Response(content=row.file_blob, media_type=row.content_type or "application/octet-stream", headers=headers)


@router.delete("/leads/{lead_id}/attachments/{attachment_id}")
def delete_lead_attachment(
    lead_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    db.delete(row)
    db.commit()
    return {"ok": True}


class AttachmentRenameBody(BaseModel):
    file_name: str


@router.patch("/leads/{lead_id}/attachments/{attachment_id}")
def rename_lead_attachment(
    lead_id: str,
    attachment_id: str,
    body: AttachmentRenameBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    next_name = (body.file_name or "").strip()
    if not next_name:
        raise HTTPException(status_code=400, detail="file_name is required")
    row.file_name = next_name[:255]
    db.commit()
    db.refresh(row)
    return row.to_dict()


class LeadUpdate(BaseModel):
    status: str | None = None
    priority: int | None = None
    assigned_to: str | None = None
    company_id: str | None = None
    notes: str | None = None
    full_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    move_date: str | None = None


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
    if body.company_id is not None and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can change lead company")

    prev_assigned_to = lead.assigned_to

    if body.status is not None:
        lead.status = body.status
    if body.priority is not None:
        lead.priority = body.priority
    if body.assigned_to is not None:
        lead.assigned_to = body.assigned_to or None
    if body.company_id is not None:
        next_company_id = body.company_id.strip()
        if not next_company_id:
            raise HTTPException(status_code=400, detail="company_id cannot be empty")
        if next_company_id not in company_ids:
            raise HTTPException(status_code=403, detail="Not allowed to move lead to this company")
        company_exists = db.query(Company.id).filter(Company.id == next_company_id).first()
        if not company_exists:
            raise HTTPException(status_code=404, detail="Company not found")

        lead.company_id = next_company_id

        # Keep assignment consistent with the lead's new company.
        if lead.assigned_to:
            rep_has_company = (
                db.query(UserCompany)
                .filter(
                    UserCompany.user_id == lead.assigned_to,
                    UserCompany.company_id == next_company_id,
                )
                .first()
            )
            if not rep_has_company:
                lead.assigned_to = None
    if body.notes is not None:
        lead.notes = body.notes
    if body.full_name is not None:
        name = body.full_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        lead.full_name = name
    if body.phone_number is not None:
        lead.phone = _normalize_phone(body.phone_number)
    if body.email is not None:
        lead.email = body.email.strip() or None
    if body.move_date is not None:
        lead.move_date = body.move_date.strip()
        lead.booked_move_date = _parse_booked_move_date(body.move_date)

    db.commit()
    db.refresh(lead)

    # If assignment changed to a new rep, send the rep_assignment SMS.
    if (
        body.assigned_to is not None
        and lead.assigned_to
        and lead.assigned_to != prev_assigned_to
    ):
        try:
            _send_rep_assignment_sms(lead, db)
        except Exception as exc:
            logger.warning("Non-fatal rep_assignment SMS failure for lead %s: %s", lead.id, exc)

    return lead.to_dict()


def _send_rep_assignment_sms(lead: Lead, db: Session) -> None:
    if not lead.phone:
        return
    rep = db.query(User).filter(User.id == lead.assigned_to).first()
    company = db.query(Company).filter(Company.id == lead.company_id).first()
    if not rep or not company:
        return

    from libs.aircall import send_sms, find_number_id

    template = get_company_template(db, company.id, "rep_assignment_sms")
    first_name = lead.full_name.split()[0] if (lead.full_name or "").strip() else ""
    message = template.format(
        first_name=first_name,
        company_name=company.name,
        company_phone=company.phone or "",
        smartmoving_id=lead.smartmoving_id or "",
        rep_name=rep.name or "",
    )

    # Prefer the rep's own Aircall number, fall back to the company's.
    nid = rep.aircall_number_id or company.aircall_number_id
    if not nid and company.phone:
        nid = find_number_id(company.phone)
        if nid:
            company.aircall_number_id = nid
            db.commit()

    sms_result = send_sms(to=lead.phone, text=message, number_id=nid)
    logger.info("Rep-assignment SMS for lead %s: %s", lead.id, sms_result)

    try:
        db.add(OutreachEvent(
            lead_id=lead.id,
            company_id=company.id,
            smartmoving_id=lead.smartmoving_id or "",
            note_id="",
            outreach_type="rep_assignment",
            job_id=lead.smartmoving_id or "",
            qualified=bool(sms_result.get("ok")),
            qualification_reason="ok" if sms_result.get("ok") else (sms_result.get("error") or "sms_failed"),
            message=message,
            messenger=False,
            aircall=True,
            dry_run=False,
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Non-fatal rep_assignment outreach log failure for lead %s: %s", lead.id, exc)


class AssignByNameRequest(BaseModel):
    name: str


@router.patch("/leads/assign-by-name/{opportunity_id}")
def assign_lead_by_name(
    opportunity_id: str,
    body: AssignByNameRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can assign leads")

    lead = db.query(Lead).filter(Lead.smartmoving_id == opportunity_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    rep = db.query(User).filter(User.name == body.name.strip()).first()
    if not rep:
        raise HTTPException(status_code=404, detail=f"User '{body.name}' not found")

    lead.assigned_to = rep.id
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
        phone=_normalize_phone(body.phone_number),
        source=body.source or "zapier",
        leadgen_id=body.leadgen_id.strip() or None,
        smartmoving_id=body.smartmoving_id.strip() or None,
        facebook_user_id=body.facebook_user_id.strip() or None,
        pickup_zip=body.pickup_zip.strip(),
        delivery_zip=body.delivery_zip.strip(),
        move_size=body.move_size.strip(),
        move_date=body.move_date.strip(),
        booked_move_date=_parse_booked_move_date(body.move_date),
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
    
    # Debug: log auto-assign decision
    any_admin_available = _any_admin_available_now(db)
    logger.info("Live lead auto-assign check: lead_id=%s any_admin_available=%s", lead.id, any_admin_available)
    
    assigned_rep = db.query(User).filter(User.id == assigned_to_user_id).first() if assigned_to_user_id else None
    sync_result = _default_sync_result()
    
    logger.info(
        "Live lead assignment state before sync: lead_id=%s mode=%s assigned_to_user_id=%s assigned_rep=%s",
        lead.id,
        assignment_mode,
        assigned_to_user_id,
        f"{assigned_rep.name}({assigned_rep.id})" if assigned_rep else None,
    )
    
    if assignment_mode == "auto":
        if not assigned_rep:
            assignment_mode = "error"
            lead.assigned_to = None
            db.commit()
            db.refresh(lead)
            sync_result = _default_sync_result("rep_not_found")
            logger.warning("Lead %s assignment failed: rep not found for id=%s", lead.id, assigned_to_user_id)
        else:
            sync_result = _sync_assignment_to_smartmoving(lead, assigned_rep)
            logger.info(
                "Live lead SmartMoving sync result: lead_id=%s rep_id=%s ok=%s error=%s status=%s",
                lead.id,
                assigned_rep.id if assigned_rep else None,
                sync_result.get("ok"),
                sync_result.get("error"),
                sync_result.get("status"),
            )
            if not sync_result.get("ok"):
                assignment_mode = "error"
                lead.assigned_to = None
                db.commit()
                db.refresh(lead)
                logger.warning(
                    "Lead %s assignment failed after rep selection: rep_id=%s error=%s",
                    lead.id,
                    assigned_rep.id,
                    sync_result.get("error", "unknown"),
                )
            else:
                logger.info("Auto-assigned lead %s to rep %s (%s)", lead.id, assigned_to_user_id, assignment_reason)
                _send_assignment_webhook_todo(lead, assigned_rep)

    # Send welcome SMS if phone and smartmoving_id are present
    sms_result = None
    if lead.phone and lead.smartmoving_id:
        from libs.aircall import send_sms, find_number_id
        first_name = lead.full_name.split()[0] if lead.full_name.strip() else ""
        template = get_company_template(db, company.id, "welcome_sms")
        message = template.format(
            first_name=first_name,
            company_name=company.name,
            smartmoving_id=lead.smartmoving_id,
            company_phone=company.phone or "",
            rep_name="",
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

    # Build assignment note with SmartMoving sync details
    assign_note = _assignment_note(assignment_mode, sync_result)
    logger.info(
        "Lead auto-assign note: lead_id=%s mode=%s note=%s sync_result=%s",
        lead.id,
        assignment_mode,
        assign_note,
        sync_result,
    )

    try:
        assign_event = AutoAssignEvent(
            lead_id=lead.id,
            company_id=company.id,
            assigned_to=lead.assigned_to,
            assignment_mode=assignment_mode,
            assignment_reason=assignment_reason,
            note=assign_note,
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

    # Duplicate lead to Top Tier Van Lines after a 10-minute delay
    if company.name == "Gorilla Haulers":
        if lead.referral_source == "Facebook-Gorilla-HHG-Nationwide":
            _enqueue_lead_for_duplication(
                lead_id=lead.id,
                target_company_name="Top Tier Van Lines",
                target_referral_source="Facebook-TTVL-HHG-Nationwide",
            )
        elif lead.referral_source == "Facebook-Gorilla-HHG-FL-GA-NC":
            _enqueue_lead_for_duplication(
                lead_id=lead.id,
                target_company_name="Top Tier Van Lines",
                target_referral_source="Facebook-TTVL-HHG-FL-GA-NC",
            )
        elif lead.referral_source == "Facebook-Gorilla-HHG-Local":
            _enqueue_lead_for_duplication(
                lead_id=lead.id,
                target_company_name="Movers 95",
                target_referral_source="Facebook-Movers95-HHG-Local",
            )

    return {
        "status": "created",
        "lead_id": lead.id,
        "full_name": lead.full_name,
        "sms": sms_result,
        "assigned_to": lead.assigned_to or "",
        "assignment_mode": assignment_mode,
        "assignment_reason": assignment_reason,
        "assignment_note": assign_note,
        "assignment_sync_result": sync_result,
    }
