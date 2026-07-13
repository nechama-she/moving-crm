import json
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3

from fastapi import APIRouter, HTTPException, Query, Depends, Header, UploadFile, File
from fastapi.responses import Response, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, cast, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from dateutil import parser as date_parser

from auth import get_current_user
from company_colors import resolve_company_color
from config import get_config
from database import get_db
from libs.common.phone import normalize_digits
from libs.smartmoving.client import get_opportunity, get_opportunity_audit_activity, get_opportunity_documents, download_opportunity_document, update_opportunity_salesperson
from models import Lead, User, UserCompany, Company, OutreachEvent, AdminUnavailability, AdminUnavailabilityRep, RepAvailabilityWindow, AutoAssignEvent, LeadAttachment, DispatchCalendarDay, LeadJob, LeadJobCharge, Followup, SentMessage, Task, AppSetting
from routes.templates import get_company_template

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Leads"])

# Statuses that dispatch can see (booked and beyond)
DISPATCH_STATUSES = {"booked", "scheduled", "completed"}
BOOKED_STATUS_CHANGED_RE = re.compile(r"\bstatus\s+changed\s+to\s+booked\b", re.IGNORECASE)

# Terminal statuses that should never receive automated messages.
NO_MESSAGE_STATUSES = {"booked", "scheduled", "completed", "lost", "cancelled"}


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


def _clean_optional_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_person_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _parse_booked_move_date(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None

    # Common compact format from imports (e.g. 20260106).
    if raw.isdigit() and len(raw) == 8:
        try:
            return datetime.strptime(raw, "%Y%m%d").date()
        except Exception:
            pass

    # Try strict ISO first, then a broad parser for varied valid date inputs.
    iso_candidate = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(iso_candidate).date()
    except Exception:
        pass

    for kwargs in (
        {"fuzzy": True, "yearfirst": True, "dayfirst": False},
        {"fuzzy": True, "yearfirst": False, "dayfirst": False},
        {"fuzzy": True, "yearfirst": False, "dayfirst": True},
    ):
        try:
            return date_parser.parse(raw, **kwargs).date()
        except Exception:
            continue
    return None


def _normalize_move_date(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = _parse_booked_move_date(raw)
    return parsed.isoformat() if parsed else raw


SMARTMOVING_STATUS_TO_CRM = {
    0: "new",
    1: "contacted",
    3: "quoted",
    4: "booked",
    10: "completed",
    11: "completed",
    20: "cancelled",
    30: "lost",
    50: "lost",
}


def _format_smartmoving_date(value) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _map_smartmoving_status(status_code) -> str:
    try:
        return SMARTMOVING_STATUS_TO_CRM.get(int(status_code), "")
    except Exception:
        return ""


def _parse_smartmoving_priority(lead_status) -> int | None:
    if lead_status in (None, ""):
        return None
    digits = "".join(ch for ch in str(lead_status) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _build_smartmoving_notes(opportunity: dict) -> str:
    parts: list[str] = []
    quote_number = opportunity.get("quoteNumber")
    referral_source = opportunity.get("referralSource")
    branch = opportunity.get("branch") or {}
    move_size = opportunity.get("moveSize") or {}
    tariff = opportunity.get("tariff") or {}

    if quote_number not in (None, ""):
        parts.append(f"quoteNumber: {quote_number}")
    if referral_source:
        parts.append(f"referralSource: {referral_source}")
    if branch.get("name"):
        parts.append(f"branchName: {str(branch.get('name')).strip()}")
    if branch.get("phoneNumber"):
        parts.append(f"branchPhone: {branch.get('phoneNumber')}")
    if move_size.get("name"):
        parts.append(f"moveSize: {move_size.get('name')}")
    if tariff.get("name"):
        parts.append(f"tariff: {str(tariff.get('name')).strip()}")
    return " | ".join(parts)


def _map_smartmoving_estimated_total(estimated_total: dict | None) -> dict:
    estimated_total = estimated_total or {}
    return {
        "subtotal": estimated_total.get("subtotal", 0),
        "taxableAmount": estimated_total.get("taxableAmount", 0),
        "tax": estimated_total.get("tax", 0),
        "finalTotal": estimated_total.get("finalTotal", 0),
    }


def _map_smartmoving_payments(payments: list | None) -> list[dict]:
    output: list[dict] = []
    for item in payments or []:
        row = {"amount": item.get("amount", 0)}
        taken_by_user = _clean_optional_text(item.get("takenByUser"))
        if taken_by_user:
            row["takenByUser"] = taken_by_user
        output.append(row)
    return output


def _merge_smartmoving_payments_with_existing(smartmoving_rows: list[dict], existing_rows: list[dict]) -> list[dict]:
    """Keep CRM-managed payment fields (repPaid/repPaidAt) when refreshing from SmartMoving."""
    merged: list[dict] = []
    for index, row in enumerate(smartmoving_rows):
        existing = existing_rows[index] if index < len(existing_rows) else {}
        rep_paid = bool(existing.get("repPaid") or False)
        rep_paid_at = str(existing.get("repPaidAt") or "").strip()

        next_row = dict(row)
        next_row["repPaid"] = rep_paid
        next_row["repPaidAt"] = rep_paid_at
        merged.append(next_row)
    return merged


def _map_smartmoving_estimated_charges(charges: list | None) -> list[dict]:
    output: list[dict] = []
    for charge in charges or []:
        mapped = {
            "sortOrder": charge.get("sortOrder", 0),
            "subtotal": charge.get("subtotal", 0),
            "discountAmount": charge.get("discountAmount", 0),
            "totalCost": charge.get("totalCost", 0),
        }
        name = _clean_optional_text(charge.get("name"))
        description = _clean_optional_text(charge.get("description"))
        editable_description = charge.get("editableDescription")
        if name:
            mapped["name"] = name
        if description:
            mapped["description"] = description
        if editable_description is not None and str(editable_description).strip():
            mapped["editableDescription"] = str(editable_description).strip()
        output.append(mapped)
    return output


def _smartmoving_job_price(job: dict) -> float:
    total = 0.0
    for charge in job.get("estimatedCharges") or []:
        try:
            total += float(charge.get("totalCost", 0) or 0)
        except Exception:
            continue
    return round(total, 2)


def _smartmoving_job_sort_order(job: dict) -> int | None:
    raw = job.get("sortOrder")
    if raw is not None:
        try:
            return int(raw)
        except Exception:
            pass

    job_number = str(job.get("jobNumber") or "").strip()
    if "-" not in job_number:
        return None
    suffix = job_number.rsplit("-", 1)[-1].strip()
    if suffix.isdigit():
        return int(suffix)
    return None


def _build_smartmoving_jobs_payload(opportunity: dict) -> list[dict]:
    jobs: list[dict] = []
    for job in opportunity.get("jobs") or []:
        addresses = job.get("jobAddresses") or []
        cleaned_addresses = [str(address).strip() for address in addresses if str(address).strip()]
        pickup = cleaned_addresses[0] if cleaned_addresses else ""
        delivery = cleaned_addresses[-1] if len(cleaned_addresses) > 1 else ""
        stops = cleaned_addresses[1:-1] if len(cleaned_addresses) > 2 else []
        move_date = _format_smartmoving_date(job.get("jobDate") or opportunity.get("serviceDate"))

        row = {
            "smartmoving_job_id": job.get("id"),
            "estimatedCharges": _map_smartmoving_estimated_charges(job.get("estimatedCharges") or []),
            "price": _smartmoving_job_price(job),
        }
        sort_order = _smartmoving_job_sort_order(job)
        if sort_order is not None:
            row["sortOrder"] = sort_order
        if pickup:
            row["pickup_zip"] = pickup
        if delivery:
            row["delivery_zip"] = delivery
        if stops:
            row["stops"] = stops
        if move_date:
            row["move_date"] = move_date
        jobs.append(row)
    return jobs


def _build_smartmoving_refresh_payload(opportunity: dict, user: User) -> dict:
    customer = opportunity.get("customer") or {}
    sales_assignee = opportunity.get("salesAssignee") or {}

    payload: dict = {}

    status = _map_smartmoving_status(opportunity.get("status"))
    if status:
        payload["status"] = status

    priority = _parse_smartmoving_priority(opportunity.get("leadStatus"))
    if priority is not None:
        payload["priority"] = priority

    assigned_to_name = _clean_optional_text(sales_assignee.get("name"))
    if assigned_to_name and user.role == "admin":
        payload["assigned_to_name"] = assigned_to_name

    move_size = _clean_optional_text((opportunity.get("moveSize") or {}).get("name"))
    if move_size:
        payload["move_size"] = move_size
    if opportunity.get("volume") is not None:
        payload["volume"] = opportunity.get("volume")
    if opportunity.get("weight") is not None:
        payload["weight"] = opportunity.get("weight")

    notes = _build_smartmoving_notes(opportunity)
    if notes:
        payload["notes"] = notes

    for key, value in (
        ("full_name", customer.get("name")),
        ("smartmoving_id", opportunity.get("id")),
        ("leadgen_id", str(opportunity.get("quoteNumber")) if opportunity.get("quoteNumber") not in (None, "") else None),
        ("phone_number", customer.get("phoneNumber")),
        ("email", customer.get("emailAddress")),
        ("referral_source", opportunity.get("referralSource")),
    ):
        clean_value = _clean_optional_text(value)
        if clean_value:
            payload[key] = clean_value

    move_type = {0: "Local", 1: "Intrastate", 2: "Interstate"}.get(opportunity.get("opportunityType"), "")
    if move_type:
        payload["move_type"] = move_type

    move_date = _format_smartmoving_date(opportunity.get("serviceDate"))
    if move_date:
        payload["move_date"] = move_date

    payload["estimatedTotal"] = _map_smartmoving_estimated_total(opportunity.get("estimatedTotal"))
    if isinstance(opportunity.get("payments"), list):
        payload["payments"] = _map_smartmoving_payments(opportunity.get("payments") or [])
    payload["jobs"] = _build_smartmoving_jobs_payload(opportunity)
    return payload


def _audit_created_at_to_local_date(created_at_utc: str, timezone_name: str) -> date | None:
    text = (created_at_utc or "").strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        created_dt = datetime.fromisoformat(text)
    except Exception:
        try:
            created_dt = date_parser.parse(text)
        except Exception:
            return None

    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=timezone.utc)

    tz_name = (timezone_name or "").strip() or "America/New_York"
    try:
        target_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        target_tz = ZoneInfo("America/New_York")

    return created_dt.astimezone(target_tz).date()


def _last_booked_date_from_audit_rows(rows: list[dict], timezone_name: str) -> date | None:
    last_date: date | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        description = str(row.get("description") or "")
        if not BOOKED_STATUS_CHANGED_RE.search(description):
            continue
        created_raw = str(row.get("createdAtUtc") or "")
        parsed = _audit_created_at_to_local_date(created_raw, timezone_name)
        if not parsed:
            continue
        if last_date is None or parsed > last_date:
            last_date = parsed
    return last_date


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


def _enqueue_lead_for_duplication(
    lead_id: str,
    target_company_name: str,
    target_referral_source: str,
    delay_minutes: int | None = None,
) -> None:
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

    if delay_minutes is not None:
        fire_at = _utcnow() + timedelta(minutes=delay_minutes)
    else:
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
        admin_rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
        if admin_rows:
            return [r[0] for r in admin_rows]
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


def _ensure_not_dispatch_write(user: User) -> None:
    if user.role == "dispatch":
        raise HTTPException(status_code=403, detail="Dispatch users are read-only")


def _effective_dispatch_date(lead: Lead) -> date | None:
    """Get the booked/service date used by dispatch calendar and search."""
    return _parse_booked_move_date(lead.move_date)


def _effective_job_date(job: LeadJob) -> date | None:
    return _parse_booked_move_date(job.move_date)


def _effective_sales_job_date(job: LeadJob) -> date | None:
    if job.booked_move_date:
        return job.booked_move_date
    return _parse_booked_move_date(job.move_date)


def _parse_move_month(value: str) -> tuple[date, date]:
    try:
        year_str, month_str = value.split("-")
        year = int(year_str)
        month = int(month_str)
        if month < 1 or month > 12:
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="move_month must be YYYY-MM")

    month_start = date(year, month, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return month_start, next_month


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

    month_start, next_month = _parse_move_month(move_month)

    allowed_company_ids = _get_user_company_ids(user, db)
    if not allowed_company_ids:
        return {"items": []}

    target_company_ids = allowed_company_ids
    if company_id:
        if company_id not in allowed_company_ids:
            raise HTTPException(status_code=403, detail="Not allowed for this company")
        target_company_ids = [company_id]

    # Dispatch calendar groups jobs by the job-level move_date.
    rows = (
        db.query(LeadJob, Lead, Company.name.label("company_name"), Company.color.label("company_color"))
        .join(Lead, Lead.id == LeadJob.lead_id)
        .join(Company, Company.id == LeadJob.company_id)
        .filter(LeadJob.company_id.in_(target_company_ids))
        .filter(Lead.status.in_(DISPATCH_STATUSES))
        .order_by(LeadJob.created_at.asc())
        .all()
    )

    filtered: list[tuple[LeadJob, Lead, str, str | None, date]] = []
    for job, lead, company_name, company_color in rows:
        effective_date = _effective_job_date(job)
        if not effective_date:
            continue
        if month_start <= effective_date < next_month:
            filtered.append((job, lead, company_name or "", company_color, effective_date))

    filtered.sort(key=lambda item: (item[4], item[0].created_at or datetime.min))

    return {
        "items": [
            {
                "id": job.id,
                "lead_id": lead.id,
                "smartmoving_id": lead.smartmoving_id or "",
                "smartmoving_job_id": job.smartmoving_job_id or "",
                "job_order": int(job.job_order or 0),
                "company_id": job.company_id,
                "company_name": company_name,
                "company_color": resolve_company_color(company_name, company_color),
                "full_name": lead.full_name or "",
                "move_date": job.move_date or "",
                "booked_move_date": job.booked_move_date.isoformat() if job.booked_move_date else "",
                "pickup_zip": job.pickup_zip or "",
                "delivery_zip": job.delivery_zip or "",
                "price": float(job.price) if job.price is not None else None,
                "volume": float(lead.volume) if lead.volume is not None else None,
                "weight": float(lead.weight) if lead.weight is not None else None,
                "estimatedTotal": _deserialize_estimated_total(lead.estimated_total),
                "payments": _deserialize_payments(lead.payments),
                "status": lead.status or "",
            }
            for job, lead, company_name, company_color, effective_date in filtered
        ]
    }


@router.get("/sales-calendar")
def get_sales_calendar(
    move_month: str = Query(default=""),  # YYYY-MM
    assigned_to: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "sales_rep", "dispatch"):
        raise HTTPException(status_code=403, detail="Sales calendar access required")

    if not move_month:
        raise HTTPException(status_code=400, detail="move_month is required")

    month_start, next_month = _parse_move_month(move_month)

    allowed_company_ids = _get_user_company_ids(user, db)
    if not allowed_company_ids:
        return {"items": []}

    rows = (
        db.query(
            LeadJob,
            Lead,
            Company.name.label("company_name"),
            Company.color.label("company_color"),
            User.id.label("assigned_to"),
            User.name.label("assigned_to_name"),
            User.role.label("assigned_to_role"),
        )
        .join(Lead, Lead.id == LeadJob.lead_id)
        .join(Company, Company.id == LeadJob.company_id)
        .outerjoin(User, User.id == Lead.assigned_to)
        .filter(LeadJob.company_id.in_(allowed_company_ids))
        .filter(LeadJob.job_order == 1)
        .filter(Lead.status.in_(DISPATCH_STATUSES))
    )

    if user.role in ("sales_rep", "dispatch"):
        rows = rows.filter(Lead.assigned_to == user.id)
    elif assigned_to:
        assigned_filter = assigned_to.strip()
        if assigned_filter == "__unassigned__":
            rows = rows.filter(Lead.assigned_to.is_(None))
        else:
            rows = rows.filter(Lead.assigned_to == assigned_filter)

    rows = rows.order_by(LeadJob.created_at.asc()).all()

    filtered: list[tuple[LeadJob, Lead, str, str | None, str | None, str | None, str | None, date]] = []
    for job, lead, company_name, company_color, assigned_to_id, assigned_to_name, assigned_to_role in rows:
        effective_date = _effective_sales_job_date(job)
        if not effective_date:
            continue
        if month_start <= effective_date < next_month:
            filtered.append((
                job,
                lead,
                company_name or "",
                company_color,
                assigned_to_id,
                assigned_to_name,
                assigned_to_role,
                effective_date,
            ))

    filtered.sort(key=lambda item: (item[7], item[0].created_at or datetime.min))

    return {
        "items": [
            {
                "id": job.id,
                "lead_id": lead.id,
                "smartmoving_id": lead.smartmoving_id or "",
                "smartmoving_job_id": job.smartmoving_job_id or "",
                "job_order": int(job.job_order or 0),
                "company_id": job.company_id,
                "company_name": company_name,
                "company_color": resolve_company_color(company_name, company_color),
                "assigned_to": assigned_to_id or "",
                "assigned_to_name": assigned_to_name or "",
                "assigned_to_role": assigned_to_role or "",
                "full_name": lead.full_name or "",
                "move_date": job.move_date or "",
                "booked_move_date": job.booked_move_date.isoformat() if job.booked_move_date else "",
                "pickup_zip": job.pickup_zip or "",
                "delivery_zip": job.delivery_zip or "",
                "price": float(job.price) if job.price is not None else None,
                "estimatedTotal": _deserialize_estimated_total(lead.estimated_total),
                "payments": _deserialize_payments(lead.payments),
                "status": lead.status or "",
            }
            for job, lead, company_name, company_color, assigned_to_id, assigned_to_name, assigned_to_role, effective_date in filtered
        ]
    }


@router.get("/dispatch-calendar-days")
def get_dispatch_calendar_days(
    company_id: str = Query(default=""),
    move_month: str = Query(default=""),  # YYYY-MM
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "dispatch"):
        raise HTTPException(status_code=403, detail="Dispatch access required")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    if not move_month:
        raise HTTPException(status_code=400, detail="move_month is required")

    allowed_company_ids = _get_user_company_ids(user, db)
    if company_id not in allowed_company_ids:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    month_start, next_month = _parse_move_month(move_month)
    rows = (
        db.query(DispatchCalendarDay)
        .filter(
            DispatchCalendarDay.company_id == company_id,
            DispatchCalendarDay.day_date >= month_start,
            DispatchCalendarDay.day_date < next_month,
        )
        .order_by(DispatchCalendarDay.day_date.asc())
        .all()
    )
    return {"items": [row.to_dict() for row in rows]}


class DispatchCalendarDayUpsert(BaseModel):
    company_id: str
    day_date: str
    is_full: bool = False
    note: str = ""


@router.put("/dispatch-calendar-days")
def upsert_dispatch_calendar_day(
    body: DispatchCalendarDayUpsert,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "dispatch"):
        raise HTTPException(status_code=403, detail="Dispatch access required")

    company_id = body.company_id.strip()
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    allowed_company_ids = _get_user_company_ids(user, db)
    if company_id not in allowed_company_ids:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    try:
        target_day = datetime.strptime((body.day_date or "").strip(), "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="day_date must be YYYY-MM-DD")

    note = (body.note or "").strip()
    row = (
        db.query(DispatchCalendarDay)
        .filter(DispatchCalendarDay.company_id == company_id, DispatchCalendarDay.day_date == target_day)
        .first()
    )

    # Keep table compact by deleting empty settings.
    if not body.is_full and not note:
        if row:
            db.delete(row)
            db.commit()
        return {"ok": True, "item": None}

    if not row:
        row = DispatchCalendarDay(
            company_id=company_id,
            day_date=target_day,
            is_full=bool(body.is_full),
            note=note or None,
            updated_by=user.id,
        )
        db.add(row)
    else:
        row.is_full = bool(body.is_full)
        row.note = note or None
        row.updated_by = user.id

    db.commit()
    db.refresh(row)
    return {"ok": True, "item": row.to_dict()}


@router.get("/dispatch-job-search")
def search_dispatch_jobs(
    query: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=25),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "dispatch", "sales_rep"):
        raise HTTPException(status_code=403, detail="Access denied")

    search = query.strip()
    if len(search) < 2:
        return {"items": []}

    allowed_company_ids = _get_user_company_ids(user, db)
    if not allowed_company_ids:
        return {"items": []}

    # Exact job-id lookup for deep-linking from lead job cards.
    exact_row = (
        db.query(LeadJob, Lead, Company.name.label("company_name"), Company.color.label("company_color"))
        .join(Lead, Lead.id == LeadJob.lead_id)
        .join(Company, LeadJob.company_id == Company.id)
        .filter(
            LeadJob.id == search,
            LeadJob.company_id.in_(allowed_company_ids),
            Lead.status.in_(DISPATCH_STATUSES),
        )
        .first()
    )
    if exact_row:
        job, lead, company_name, company_color = exact_row
        if user.role == "sales_rep" and lead.assigned_to != user.id:
            return {"items": []}
        effective_date = _effective_job_date(job)
        if not effective_date:
            return {"items": []}
        return {
            "items": [
                {
                    "id": job.id,
                    "lead_id": lead.id,
                    "job_order": int(job.job_order or 0),
                    "company_id": job.company_id,
                    "company_name": company_name or "",
                    "company_color": resolve_company_color(company_name, company_color),
                    "full_name": lead.full_name or "",
                    "booked_move_date": job.booked_move_date.isoformat() if job.booked_move_date else "",
                    "move_date": job.move_date or "",
                    "pickup_zip": job.pickup_zip or "",
                    "delivery_zip": job.delivery_zip or "",
                    "price": float(job.price) if job.price is not None else None,
                    "status": lead.status or "",
                    "leadgen_id": lead.leadgen_id or "",
                }
            ]
        }

    pattern = f"%{search.lower()}%"
    rows = (
        db.query(LeadJob, Lead, Company.name.label("company_name"), Company.color.label("company_color"))
        .join(Lead, Lead.id == LeadJob.lead_id)
        .join(Company, LeadJob.company_id == Company.id)
        .filter(
            LeadJob.company_id.in_(allowed_company_ids),
            Lead.status.in_(DISPATCH_STATUSES),
            (
                Lead.full_name.ilike(pattern)
                | Lead.leadgen_id.ilike(pattern)
                | Lead.smartmoving_id.ilike(pattern)
                | LeadJob.id.ilike(pattern)
                | LeadJob.pickup_zip.ilike(pattern)
                | LeadJob.delivery_zip.ilike(pattern)
            ),
        )
        .order_by(LeadJob.created_at.desc())
        .all()
    )

    if user.role == "sales_rep":
        rows = [(job, lead, company_name, company_color) for job, lead, company_name, company_color in rows if lead.assigned_to == user.id]

    items: list[dict] = []
    for job, lead, company_name, company_color in rows:
        effective_date = _effective_job_date(job)
        if not effective_date:
            continue
        items.append(
            {
                "id": job.id,
                "lead_id": lead.id,
                "job_order": int(job.job_order or 0),
                "company_id": job.company_id,
                "company_name": company_name or "",
                "company_color": resolve_company_color(company_name, company_color),
                "full_name": lead.full_name or "",
                "booked_move_date": job.booked_move_date.isoformat() if job.booked_move_date else "",
                "move_date": job.move_date or "",
                "pickup_zip": job.pickup_zip or "",
                "delivery_zip": job.delivery_zip or "",
                "price": float(job.price) if job.price is not None else None,
                "status": lead.status or "",
                "leadgen_id": lead.leadgen_id or "",
            }
        )
        if len(items) >= limit:
            break

    return {"items": items}


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


@router.get("/leads/by-smartmoving/{smartmoving_id}")
def get_lead_by_smartmoving(smartmoving_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.smartmoving_id == smartmoving_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead.to_dict()


@router.delete("/leads/by-smartmoving/{smartmoving_id}")
def delete_lead_by_smartmoving(
    smartmoving_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete leads")

    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.smartmoving_id == smartmoving_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    _hard_delete_lead(lead, db)
    return {"ok": True, "deleted_lead_id": lead.id}


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


@router.delete("/leads/{lead_id}")
def delete_lead(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete leads")

    lead = _get_visible_lead_or_404(lead_id, user, db)

    _hard_delete_lead(lead, db)
    return {"ok": True, "deleted_lead_id": lead.id}


def _hard_delete_lead(lead: Lead, db: Session) -> None:
    smartmoving_id = (lead.smartmoving_id or "").strip()
    resolved_lead_id = lead.id

    try:
        job_ids = [
            row[0]
            for row in db.query(LeadJob.id).filter(LeadJob.lead_id == resolved_lead_id).all()
            if row and row[0]
        ]
        if job_ids:
            db.query(LeadJobCharge).filter(LeadJobCharge.job_id.in_(job_ids)).delete(synchronize_session=False)

        db.query(LeadAttachment).filter(LeadAttachment.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(LeadJob).filter(LeadJob.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(Task).filter(Task.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(AutoAssignEvent).filter(AutoAssignEvent.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(OutreachEvent).filter(OutreachEvent.lead_id == resolved_lead_id).delete(synchronize_session=False)

        if smartmoving_id:
            db.query(Followup).filter(Followup.smartmoving_id == smartmoving_id).delete(synchronize_session=False)
            db.query(SentMessage).filter(SentMessage.smartmoving_id == smartmoving_id).delete(synchronize_session=False)
            db.query(OutreachEvent).filter(OutreachEvent.smartmoving_id == smartmoving_id).delete(synchronize_session=False)

        db.delete(lead)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to hard-delete lead %s", resolved_lead_id)
        raise HTTPException(status_code=500, detail="Failed to delete lead")


MAX_ATTACHMENT_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
JOB_PICKUPS_SETTING_PREFIX = "lead_job_pickups:"
JOB_DELIVERIES_SETTING_PREFIX = "lead_job_deliveries:"
JOB_STOPS_SETTING_PREFIX = "lead_job_stops:"


def _get_visible_lead_or_404(lead_id: str, user: User, db: Session) -> Lead:
    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        lead = db.query(Lead).filter(Lead.leadgen_id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def _next_lead_job_order(lead_id: str, db: Session) -> int:
    max_order = db.query(func.max(LeadJob.job_order)).filter(LeadJob.lead_id == lead_id).scalar()
    return (int(max_order) if max_order is not None else 0) + 1


def _get_or_create_primary_lead_job(lead: Lead, db: Session) -> LeadJob:
    row = (
        db.query(LeadJob)
        .filter(LeadJob.lead_id == lead.id, LeadJob.job_order == 1)
        .first()
    )
    if row:
        return row

    row = LeadJob(
        lead_id=lead.id,
        company_id=lead.company_id,
        job_order=1,
        pickup_zip=lead.pickup_zip,
        delivery_zip=lead.delivery_zip,
        move_date=lead.move_date,
        booked_move_date=lead.booked_move_date,
        price=None,
    )
    db.add(row)
    return row


class LeadJobChargePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = ""
    description: str = ""
    editable_description: str | None = Field(default=None, alias="editableDescription")
    sort_order: int = Field(default=0, alias="sortOrder")
    subtotal: float = 0
    discount_amount: float = Field(default=0, alias="discountAmount")
    total_cost: float = Field(default=0, alias="totalCost")


class LeadJobChargesBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    estimated_charges: list[LeadJobChargePayload] = Field(default_factory=list, alias="estimatedCharges")


class EstimatedTotalPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    subtotal: float = 0
    taxable_amount: float = Field(default=0, alias="taxableAmount")
    tax: float = 0
    final_total: float = Field(default=0, alias="finalTotal")


class LeadPaymentPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    amount: float = 0
    taken_by_user: str = Field(default="", alias="takenByUser")
    rep_paid: bool = Field(default=False, alias="repPaid")
    rep_paid_at: str = Field(default="", alias="repPaidAt")


def _serialize_estimated_total(payload: EstimatedTotalPayload | None) -> str | None:
    if payload is None:
        return None
    return json.dumps({
        "subtotal": float(payload.subtotal),
        "taxableAmount": float(payload.taxable_amount),
        "tax": float(payload.tax),
        "finalTotal": float(payload.final_total),
    })


def _serialize_payments(payments: list[LeadPaymentPayload] | None) -> str | None:
    if payments is None:
        return None
    return json.dumps([
        {
            "amount": float(payment.amount),
            "takenByUser": (payment.taken_by_user or "").strip(),
            "repPaid": bool(payment.rep_paid),
            "repPaidAt": (payment.rep_paid_at or "").strip(),
        }
        for payment in payments
    ])


def _deserialize_estimated_total(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        "subtotal": float(parsed.get("subtotal") or 0),
        "taxableAmount": float(parsed.get("taxableAmount") or 0),
        "tax": float(parsed.get("tax") or 0),
        "finalTotal": float(parsed.get("finalTotal") or 0),
    }


def _deserialize_payments(raw: str | None) -> list[dict[str, object]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    payments: list[dict[str, object]] = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        payments.append({
            "amount": float(row.get("amount") or 0),
            "takenByUser": str(row.get("takenByUser") or "").strip(),
            "repPaid": bool(row.get("repPaid") or False),
            "repPaidAt": str(row.get("repPaidAt") or "").strip(),
        })
    return payments


def _to_money_decimal(value: float | int | str | None, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid number")
    return amount


def _replace_job_charges(job: LeadJob, charges: list[LeadJobChargePayload | dict], db: Session) -> None:
    if not job.id:
        db.flush()

    db.query(LeadJobCharge).filter(LeadJobCharge.job_id == job.id).delete(synchronize_session=False)

    for index, charge in enumerate(charges):
        if isinstance(charge, dict):
            charge = LeadJobChargePayload.model_validate(charge)

        display_name = (charge.editable_description or "").strip() or (charge.name or "").strip()
        if not display_name:
            continue
        db.add(LeadJobCharge(
            job_id=job.id,
            name=display_name,
            description=(charge.description or "").strip(),
            sort_order=int(charge.sort_order if charge.sort_order is not None else index),
            subtotal=_to_money_decimal(charge.subtotal, "subtotal"),
            discount_amount=_to_money_decimal(charge.discount_amount, "discount_amount"),
            total_cost=_to_money_decimal(charge.total_cost, "total_cost"),
        ))


class LeadJobCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    company_id: str | None = None
    smartmoving_job_id: str = ""
    pickup_zip: str = ""
    delivery_zip: str = ""
    stops: list[str] = Field(default_factory=list)
    pickup_addresses: list[str] = Field(default_factory=list, alias="pickupAddresses")
    delivery_addresses: list[str] = Field(default_factory=list, alias="deliveryAddresses")
    move_date: str = ""
    booked_move_date: str = ""
    price: float | None = None


class LeadJobUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    company_id: str | None = None
    smartmoving_job_id: str | None = None
    pickup_zip: str | None = None
    delivery_zip: str | None = None
    stops: list[str] | None = None
    pickup_addresses: list[str] | None = Field(default=None, alias="pickupAddresses")
    delivery_addresses: list[str] | None = Field(default=None, alias="deliveryAddresses")
    move_date: str | None = None
    booked_move_date: str | None = None
    price: float | None = None


def _job_pickups_setting_key(job_id: str) -> str:
    return f"{JOB_PICKUPS_SETTING_PREFIX}{job_id}"


def _job_deliveries_setting_key(job_id: str) -> str:
    return f"{JOB_DELIVERIES_SETTING_PREFIX}{job_id}"


def _job_stops_setting_key(job_id: str) -> str:
    return f"{JOB_STOPS_SETTING_PREFIX}{job_id}"


def _normalize_address_list(value: list[str] | None, fallback_single: str | None = "") -> list[str]:
    ordered: list[str] = []
    for entry in (value or []):
        text = _clean_optional_text(entry)
        if text:
            ordered.append(text)
    if ordered:
        return ordered
    fallback = _clean_optional_text(fallback_single)
    return [fallback] if fallback else []


def _normalize_stops_list(value: list[str] | None) -> list[str]:
    out: list[str] = []
    for entry in (value or []):
        text = _clean_optional_text(entry)
        if text:
            out.append(text)
    return out


def _read_addresses_from_setting(db: Session, key: str) -> list[str]:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row or not (row.value or "").strip():
        return []
    try:
        parsed = json.loads(row.value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    for entry in parsed:
        text = _clean_optional_text(str(entry))
        if text:
            out.append(text)
    return out


def _write_addresses_to_setting(db: Session, key: str, addresses: list[str]) -> None:
    existing = db.query(AppSetting).filter(AppSetting.key == key).first()
    serialized = json.dumps(addresses)
    if existing:
        existing.value = serialized
    else:
        db.add(AppSetting(key=key, value=serialized))


def _persist_job_address_lists(db: Session, job_id: str, pickups: list[str], deliveries: list[str]) -> None:
    _write_addresses_to_setting(db, _job_pickups_setting_key(job_id), pickups)
    _write_addresses_to_setting(db, _job_deliveries_setting_key(job_id), deliveries)


def _read_job_route(db: Session, job: LeadJob) -> tuple[str, list[str], str]:
    pickup = _clean_optional_text(job.pickup_zip)
    delivery = _clean_optional_text(job.delivery_zip)
    stops = _read_addresses_from_setting(db, _job_stops_setting_key(job.id))

    if not stops:
        legacy_pickups = _read_addresses_from_setting(db, _job_pickups_setting_key(job.id))
        legacy_deliveries = _read_addresses_from_setting(db, _job_deliveries_setting_key(job.id))
        route = [*legacy_pickups, *legacy_deliveries]
        if route:
            if not pickup:
                pickup = route[0]
            if not delivery:
                delivery = route[-1]
            if len(route) > 2:
                stops = route[1:-1]

    return pickup, stops, delivery


def _persist_job_route(db: Session, job_id: str, pickup: str, stops: list[str], delivery: str) -> None:
    _write_addresses_to_setting(db, _job_pickups_setting_key(job_id), [pickup] if pickup else [])
    _write_addresses_to_setting(db, _job_deliveries_setting_key(job_id), [delivery] if delivery else [])
    _write_addresses_to_setting(db, _job_stops_setting_key(job_id), _normalize_stops_list(stops))


def _serialize_job_with_addresses(job: LeadJob, db: Session) -> dict:
    payload = job.to_dict()
    pickup, stops, delivery = _read_job_route(db, job)
    payload["pickup_zip"] = pickup
    payload["delivery_zip"] = delivery
    payload["stops"] = [{"order": index + 1, "address": address} for index, address in enumerate(stops)]
    return payload


@router.get("/leads/{lead_id}/jobs")
def list_lead_jobs(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    _get_or_create_primary_lead_job(lead, db)
    db.commit()

    rows = (
        db.query(LeadJob)
        .filter(LeadJob.lead_id == lead.id)
        .order_by(LeadJob.job_order.asc(), LeadJob.created_at.asc())
        .all()
    )
    return {"items": [_serialize_job_with_addresses(row, db) for row in rows]}


@router.post("/leads/{lead_id}/jobs")
def create_lead_job(
    lead_id: str,
    body: LeadJobCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    company_ids = _get_user_company_ids(user, db)

    company_id = (body.company_id or "").strip() or lead.company_id
    if company_id not in company_ids:
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    company_exists = db.query(Company.id).filter(Company.id == company_id).first()
    if not company_exists:
        raise HTTPException(status_code=404, detail="Company not found")

    move_date = _normalize_move_date(body.move_date)
    booked_date_raw = (body.booked_move_date or "").strip()
    booked_date = _parse_booked_move_date(booked_date_raw)
    if booked_date_raw and not booked_date:
        raise HTTPException(status_code=400, detail="booked_move_date must be a valid date")

    price_value = None
    if body.price is not None:
        try:
            price_value = Decimal(str(body.price)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=400, detail="price must be a valid number")
        if price_value < 0:
            raise HTTPException(status_code=400, detail="price must be >= 0")

    row = LeadJob(
        lead_id=lead.id,
        company_id=company_id,
        job_order=_next_lead_job_order(lead.id, db),
        smartmoving_job_id=(body.smartmoving_job_id or "").strip() or None,
        pickup_zip="",
        delivery_zip="",
        move_date=move_date,
        booked_move_date=booked_date,
        price=price_value,
    )

    pickup = _clean_optional_text(body.pickup_zip)
    delivery = _clean_optional_text(body.delivery_zip)
    stops = _normalize_stops_list(body.stops)
    if body.pickup_addresses or body.delivery_addresses:
        route = [
            *_normalize_address_list(body.pickup_addresses, pickup),
            *_normalize_address_list(body.delivery_addresses, delivery),
        ]
        if route:
            pickup = route[0]
            delivery = route[-1] if len(route) > 1 else ""
            stops = route[1:-1] if len(route) > 2 else []

    if not pickup:
        raise HTTPException(status_code=400, detail="At least one pickup address is required")
    if not delivery:
        raise HTTPException(status_code=400, detail="At least one delivery address is required")
    row.pickup_zip = pickup
    row.delivery_zip = delivery

    db.add(row)
    db.flush()
    _persist_job_route(db, row.id, pickup, stops, delivery)
    db.commit()
    db.refresh(row)
    return _serialize_job_with_addresses(row, db)


@router.put("/leads/{lead_id}/jobs/{job_id}/charges")
def replace_lead_job_charges(
    lead_id: str,
    job_id: str,
    body: LeadJobChargesBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadJob)
        .filter(LeadJob.id == job_id, LeadJob.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    _replace_job_charges(row, body.estimated_charges, db)
    db.commit()
    db.refresh(row)
    return _serialize_job_with_addresses(row, db)


@router.patch("/leads/{lead_id}/jobs/{job_id}")
def update_lead_job(
    lead_id: str,
    job_id: str,
    body: LeadJobUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadJob)
        .filter(LeadJob.id == job_id, LeadJob.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    payload = body.model_dump(exclude_unset=True, by_alias=False)
    company_ids = _get_user_company_ids(user, db)

    if "company_id" in payload:
        next_company_id = (payload.get("company_id") or "").strip()
        if not next_company_id:
            raise HTTPException(status_code=400, detail="company_id cannot be empty")
        if next_company_id not in company_ids:
            raise HTTPException(status_code=403, detail="Not allowed for this company")
        company_exists = db.query(Company.id).filter(Company.id == next_company_id).first()
        if not company_exists:
            raise HTTPException(status_code=404, detail="Company not found")
        row.company_id = next_company_id

    if "smartmoving_job_id" in payload:
        row.smartmoving_job_id = (payload.get("smartmoving_job_id") or "").strip() or None

    current_pickup, current_stops, current_delivery = _read_job_route(db, row)
    next_pickup = current_pickup
    next_stops = current_stops
    next_delivery = current_delivery

    if "pickup_zip" in payload:
        next_pickup = _clean_optional_text(payload.get("pickup_zip") or "")
    if "delivery_zip" in payload:
        next_delivery = _clean_optional_text(payload.get("delivery_zip") or "")
    if "stops" in payload:
        next_stops = _normalize_stops_list(payload.get("stops") or [])

    if "pickup_addresses" in payload or "delivery_addresses" in payload:
        route = [
            *_normalize_address_list(payload.get("pickup_addresses") or [], next_pickup),
            *_normalize_address_list(payload.get("delivery_addresses") or [], next_delivery),
        ]
        if route:
            next_pickup = route[0]
            next_delivery = route[-1] if len(route) > 1 else ""
            next_stops = route[1:-1] if len(route) > 2 else []

    if not next_pickup:
        raise HTTPException(status_code=400, detail="At least one pickup address is required")
    if not next_delivery:
        raise HTTPException(status_code=400, detail="At least one delivery address is required")

    row.pickup_zip = next_pickup
    row.delivery_zip = next_delivery
    if "move_date" in payload:
        row.move_date = _normalize_move_date(payload.get("move_date") or "")

    if "booked_move_date" in payload:
        booked_raw = (payload.get("booked_move_date") or "").strip()
        if not booked_raw:
            row.booked_move_date = None
        else:
            booked = _parse_booked_move_date(booked_raw)
            if not booked:
                raise HTTPException(status_code=400, detail="booked_move_date must be a valid date")
            row.booked_move_date = booked

    if "price" in payload:
        price_raw = payload.get("price")
        if price_raw is None:
            row.price = None
        else:
            try:
                price_value = Decimal(str(price_raw)).quantize(Decimal("0.01"))
            except (InvalidOperation, ValueError):
                raise HTTPException(status_code=400, detail="price must be a valid number")
            if price_value < 0:
                raise HTTPException(status_code=400, detail="price must be >= 0")
            row.price = price_value

    _persist_job_route(db, row.id, next_pickup, next_stops, next_delivery)

    db.commit()
    db.refresh(row)
    return _serialize_job_with_addresses(row, db)


@router.delete("/leads/{lead_id}/jobs/{job_id}")
def delete_lead_job(
    lead_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadJob)
        .filter(LeadJob.id == job_id, LeadJob.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row.job_order == 1:
        raise HTTPException(status_code=400, detail="Cannot delete primary lead job")

    pickups_setting = db.query(AppSetting).filter(AppSetting.key == _job_pickups_setting_key(row.id)).first()
    if pickups_setting:
        db.delete(pickups_setting)
    deliveries_setting = db.query(AppSetting).filter(AppSetting.key == _job_deliveries_setting_key(row.id)).first()
    if deliveries_setting:
        db.delete(deliveries_setting)
    stops_setting = db.query(AppSetting).filter(AppSetting.key == _job_stops_setting_key(row.id)).first()
    if stops_setting:
        db.delete(stops_setting)

    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Job-level attachment endpoints
# ---------------------------------------------------------------------------

class AttachmentRenameBody(BaseModel):
    file_name: str


def _get_job_or_404(lead_id: str, job_id: str, user: User, db: Session) -> "LeadJob":
    lead = _get_visible_lead_or_404(lead_id, user, db)
    job = (
        db.query(LeadJob)
        .filter(LeadJob.id == job_id, LeadJob.lead_id == lead.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _ensure_attachment_job_column(db: Session) -> None:
    """Ensure lead_attachments.job_id exists even if migration has not run yet."""
    try:
        db.execute(text("ALTER TABLE lead_attachments ADD COLUMN IF NOT EXISTS job_id VARCHAR(36)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_attachments_job_id ON lead_attachments (job_id)"))
        db.commit()
    except Exception:
        db.rollback()


def _ensure_attachment_link_columns(db: Session) -> None:
    """Ensure link metadata columns exist for external attachments."""
    try:
        db.execute(text("ALTER TABLE lead_attachments ADD COLUMN IF NOT EXISTS external_url TEXT"))
        db.execute(text("ALTER TABLE lead_attachments ADD COLUMN IF NOT EXISTS is_external_link BOOLEAN NOT NULL DEFAULT FALSE"))
        db.execute(text("ALTER TABLE lead_attachments ADD COLUMN IF NOT EXISTS external_source VARCHAR(50)"))
        db.execute(text("ALTER TABLE lead_attachments ADD COLUMN IF NOT EXISTS source_external_id VARCHAR(255)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_attachments_external_source ON lead_attachments (external_source)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_lead_attachments_source_external_id ON lead_attachments (source_external_id)"))
        db.commit()
    except Exception:
        db.rollback()


def _extract_smartmoving_document_links(payload: object) -> list[dict[str, str]]:
    """Extract document links from unknown SmartMoving documents payload shapes."""
    candidates: list[dict] = []

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            lower_keys = {str(key).lower() for key in node.keys()}
            if any(key in lower_keys for key in ("url", "link", "documenturl", "downloadurl", "fileurl", "publicurl", "href", "uri")):
                candidates.append(node)
            for value in node.values():
                walk(value)

    def pick_text(row: dict, keys: tuple[str, ...]) -> str:
        for key in keys:
            for variant in (key, key.lower(), key.upper()):
                value = row.get(variant)
                if value not in (None, ""):
                    text_value = str(value).strip()
                    if text_value:
                        return text_value
        return ""

    walk(payload)

    extracted: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in candidates:
        url = pick_text(row, ("url", "link", "documentUrl", "downloadUrl", "fileUrl", "publicUrl", "href", "uri"))
        if not url.lower().startswith(("http://", "https://")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        extracted.append({
            "external_id": pick_text(row, ("id", "documentId", "fileId", "guid", "documentGuid")),
            "name": pick_text(row, ("fileName", "name", "title", "documentName")) or "SmartMoving Document",
            "url": url,
            "smartmoving_job_id": pick_text(row, ("smartmovingJobId", "jobId", "opportunityJobId")),
        })
    return extracted


def _sync_smartmoving_document_links(lead: Lead, user: User, db: Session) -> int:
    """Upsert SmartMoving document links into job attachments without storing blobs."""
    smartmoving_id = _clean_optional_text(lead.smartmoving_id)
    if not smartmoving_id:
        return 0

    result = get_opportunity_documents(smartmoving_id)
    if result.get("error"):
        logger.warning("SmartMoving documents sync failed for lead %s: %s", lead.id, result.get("error"))
        return 0

    documents = _extract_smartmoving_document_links(result.get("data"))
    if not documents:
        return 0

    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)

    jobs = (
        db.query(LeadJob)
        .filter(LeadJob.lead_id == lead.id)
        .order_by(LeadJob.job_order.asc(), LeadJob.created_at.asc())
        .all()
    )
    if not jobs:
        return 0

    primary_job = jobs[0]
    job_by_smartmoving_id = {
        (row.smartmoving_job_id or "").strip(): row
        for row in jobs
        if (row.smartmoving_job_id or "").strip()
    }

    existing_rows = (
        db.query(LeadAttachment)
        .filter(
            LeadAttachment.lead_id == lead.id,
            LeadAttachment.external_source == "smartmoving",
        )
        .all()
    )
    existing_keys = set()
    for row in existing_rows:
        key = (
            row.job_id or "",
            (row.source_external_id or "").strip() or (row.external_url or "").strip(),
        )
        if key[1]:
            existing_keys.add(key)

    created = 0
    for doc in documents:
        target_job = job_by_smartmoving_id.get((doc.get("smartmoving_job_id") or "").strip()) or primary_job
        key_value = (doc.get("external_id") or "").strip() or (doc.get("url") or "").strip()
        dedupe_key = (target_job.id, key_value)
        if not key_value or dedupe_key in existing_keys:
            continue
        existing_keys.add(dedupe_key)

        row = LeadAttachment(
            lead_id=lead.id,
            job_id=target_job.id,
            file_name=(doc.get("name") or "SmartMoving Document")[:255],
            content_type="application/x-smartmoving-link",
            file_size=0,
            file_blob=b"",
            external_url=(doc.get("url") or "")[:2048],
            is_external_link=True,
            external_source="smartmoving",
            source_external_id=(doc.get("external_id") or "")[:255] or None,
            uploaded_by=user.id,
        )
        db.add(row)
        created += 1

    if created:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to save SmartMoving document links for lead %s", lead.id)
            return 0

    return created


def _download_external_attachment_or_redirect(lead: Lead, row: LeadAttachment) -> Response:
    external_url = (getattr(row, "external_url", "") or "").strip()
    is_external = bool(getattr(row, "is_external_link", False))
    if not is_external or not external_url:
        safe_name = (row.file_name or "attachment").replace('"', "")
        headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
        return Response(content=row.file_blob, media_type=row.content_type or "application/octet-stream", headers=headers)

    if (getattr(row, "external_source", "") or "").strip().lower() == "smartmoving":
        smartmoving_id = _clean_optional_text(lead.smartmoving_id)
        document_id = (getattr(row, "source_external_id", "") or "").strip()
        if smartmoving_id:
            fetched = download_opportunity_document(
                smartmoving_id,
                document_id=document_id,
                document_url=external_url,
            )
            if fetched.get("ok"):
                content = fetched.get("content") or b""
                content_type = str(fetched.get("content_type") or row.content_type or "application/octet-stream")
                file_name = str(fetched.get("file_name") or row.file_name or "attachment").replace('"', "")
                headers = {"Content-Disposition": f'inline; filename="{file_name}"'}
                return Response(content=content, media_type=content_type, headers=headers)

    # Fallback keeps previous behavior when server-side fetch is not possible.
    return RedirectResponse(url=external_url, status_code=307)


def _backfill_attachment_jobs_for_lead(lead_id: str, db: Session) -> None:
    """Map legacy lead-level attachments to the lead primary job (job_order=1)."""
    primary_job = (
        db.query(LeadJob)
        .filter(LeadJob.lead_id == lead_id, LeadJob.job_order == 1)
        .first()
    )
    if not primary_job:
        return
    try:
        db.execute(
            text(
                "UPDATE lead_attachments "
                "SET job_id = :job_id "
                "WHERE lead_id = :lead_id AND (job_id IS NULL OR job_id = '')"
            ),
            {"job_id": primary_job.id, "lead_id": lead_id},
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("/leads/{lead_id}/jobs/{job_id}/attachments")
def list_job_attachments(
    lead_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)
    _backfill_attachment_jobs_for_lead(lead_id, db)
    job = _get_job_or_404(lead_id, job_id, user, db)
    rows = (
        db.query(LeadAttachment, User)
        .outerjoin(User, LeadAttachment.uploaded_by == User.id)
        .filter(LeadAttachment.job_id == job.id)
        .order_by(LeadAttachment.created_at.desc())
        .all()
    )
    items = []
    for attachment, uploader in rows:
        item = attachment.to_dict()
        item["uploaded_by_name"] = uploader.name if uploader else ""
        items.append(item)
    return {"items": items}


@router.post("/leads/{lead_id}/jobs/{job_id}/attachments")
def upload_job_attachment(
    lead_id: str,
    job_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)
    _backfill_attachment_jobs_for_lead(lead_id, db)
    job = _get_job_or_404(lead_id, job_id, user, db)

    file_name = (file.filename or "").strip()
    if not file_name:
        raise HTTPException(status_code=400, detail="File name is required")

    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(payload) > MAX_ATTACHMENT_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 15 MB)")

    row = LeadAttachment(
        lead_id=lead_id,
        job_id=job.id,
        file_name=file_name,
        content_type=(file.content_type or "application/octet-stream"),
        file_size=len(payload),
        file_blob=payload,
        uploaded_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    item = row.to_dict()
    item["uploaded_by_name"] = user.name if user else ""
    return item


@router.get("/leads/{lead_id}/jobs/{job_id}/attachments/{attachment_id}/download")
def download_job_attachment(
    lead_id: str,
    job_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)
    _backfill_attachment_jobs_for_lead(lead_id, db)
    job = _get_job_or_404(lead_id, job_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.job_id == job.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    lead = _get_visible_lead_or_404(lead_id, user, db)
    return _download_external_attachment_or_redirect(lead, row)


@router.delete("/leads/{lead_id}/jobs/{job_id}/attachments/{attachment_id}")
def delete_job_attachment(
    lead_id: str,
    job_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)
    _backfill_attachment_jobs_for_lead(lead_id, db)
    job = _get_job_or_404(lead_id, job_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.job_id == job.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.patch("/leads/{lead_id}/jobs/{job_id}/attachments/{attachment_id}")
def rename_job_attachment(
    lead_id: str,
    job_id: str,
    attachment_id: str,
    body: AttachmentRenameBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)
    _backfill_attachment_jobs_for_lead(lead_id, db)
    job = _get_job_or_404(lead_id, job_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.job_id == job.id)
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


@router.get("/leads/{lead_id}/attachments")
def list_lead_attachments(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_attachment_link_columns(db)
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
    _ensure_attachment_link_columns(db)
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
    _ensure_attachment_link_columns(db)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return _download_external_attachment_or_redirect(lead, row)


@router.delete("/leads/{lead_id}/attachments/{attachment_id}")
def delete_lead_attachment(
    lead_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_attachment_link_columns(db)
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


@router.patch("/leads/{lead_id}/attachments/{attachment_id}")
def rename_lead_attachment(
    lead_id: str,
    attachment_id: str,
    body: AttachmentRenameBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_attachment_link_columns(db)
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


class LeadUpdateJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    sort_order: int | None = Field(default=None, alias="sortOrder")
    smartmoving_job_id: str | None = None
    pickup_zip: str | None = None
    delivery_zip: str | None = None
    stops: list[str] | None = None
    pickup_addresses: list[str] | None = Field(default=None, alias="pickupAddresses")
    delivery_addresses: list[str] | None = Field(default=None, alias="deliveryAddresses")
    move_date: str | None = None
    booked_move_date: str | None = None
    price: float | None = None
    estimated_charges: list[LeadJobChargePayload] | None = Field(default=None, alias="estimatedCharges")


class LeadUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str | None = None
    priority: int | None = None
    assigned_to: str | None = None
    assigned_to_name: str | None = None
    company_id: str | None = None
    company_name: str | None = None
    notes: str | None = None
    full_name: str | None = None
    leadgen_id: str | None = None
    smartmoving_id: str | None = None
    phone_number: str | None = None
    email: str | None = None
    move_size: str | None = None
    volume: float | None = None
    weight: float | None = None
    move_date: str | None = None
    booked_move_date: str | None = None
    move_type: str | None = None
    referral_source: str | None = None
    jobs: list[LeadUpdateJob] | None = None
    estimated_total: EstimatedTotalPayload | None = Field(default=None, alias="estimatedTotal")
    payments: list[LeadPaymentPayload] | None = None


@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: str,
    body: LeadUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    company_ids = _get_user_company_ids(user, db)
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id.in_(company_ids)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Only admin can assign leads
    if (body.assigned_to is not None or body.assigned_to_name is not None) and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can assign leads")
    if (body.company_id is not None or body.company_name is not None) and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can change lead company")

    prev_assigned_to = lead.assigned_to

    if body.status is not None:
        lead.status = body.status
    if body.priority is not None:
        lead.priority = body.priority
    if body.assigned_to is not None and body.assigned_to_name is not None:
        raise HTTPException(status_code=400, detail="Provide either assigned_to or assigned_to_name, not both")
    if body.assigned_to is not None:
        lead.assigned_to = body.assigned_to or None
    elif body.assigned_to_name is not None:
        requested_name = body.assigned_to_name.strip()
        if not requested_name:
            lead.assigned_to = None
        else:
            users = db.query(User).all()
            needle = _normalize_person_name(requested_name)
            matched_users = [u for u in users if _normalize_person_name(u.name) == needle]
            if not matched_users:
                raise HTTPException(status_code=400, detail=f"assigned_to_name '{requested_name}' not found")
            if len(matched_users) > 1:
                raise HTTPException(status_code=400, detail="assigned_to_name is ambiguous; send assigned_to user id")
            lead.assigned_to = matched_users[0].id
    if body.company_id is not None and body.company_name is not None:
        raise HTTPException(status_code=400, detail="Provide either company_id or company_name, not both")

    next_company_id: str | None = None
    if body.company_id is not None:
        next_company_id = body.company_id.strip()
        if not next_company_id:
            raise HTTPException(status_code=400, detail="company_id cannot be empty")
    elif body.company_name is not None:
        requested_company_name = body.company_name.strip()
        if not requested_company_name:
            raise HTTPException(status_code=400, detail="company_name cannot be empty")
        company = (
            db.query(Company)
            .filter(func.lower(Company.name) == requested_company_name.lower())
            .first()
        )
        if not company:
            raise HTTPException(status_code=404, detail=f"company_name '{requested_company_name}' not found")
        next_company_id = company.id

    if next_company_id is not None:
        if next_company_id not in company_ids:
            raise HTTPException(status_code=403, detail="Not allowed to move lead to this company")

        lead.company_id = next_company_id

        # Keep assignment consistent with the lead's new company.
        if lead.assigned_to:
            assigned_user = db.query(User).filter(User.id == lead.assigned_to).first()
            if assigned_user and assigned_user.role == "sales_rep":
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
    if body.leadgen_id is not None:
        lead.leadgen_id = body.leadgen_id.strip() or None
    if body.smartmoving_id is not None:
        lead.smartmoving_id = body.smartmoving_id.strip() or None
    if body.phone_number is not None:
        lead.phone = _normalize_phone(body.phone_number)
    if body.email is not None:
        lead.email = body.email.strip() or None
    if body.move_size is not None:
        lead.move_size = body.move_size.strip()
    if body.volume is not None:
        volume_value = _to_money_decimal(body.volume, "volume")
        if volume_value < 0:
            raise HTTPException(status_code=400, detail="volume must be >= 0")
        lead.volume = volume_value
    if body.weight is not None:
        weight_value = _to_money_decimal(body.weight, "weight")
        if weight_value < 0:
            raise HTTPException(status_code=400, detail="weight must be >= 0")
        lead.weight = weight_value
    if body.move_date is not None:
        lead.move_date = _normalize_move_date(body.move_date)
    if body.booked_move_date is not None:
        booked_raw = (body.booked_move_date or "").strip()
        if not booked_raw:
            lead.booked_move_date = None
        else:
            parsed_booked = _parse_booked_move_date(booked_raw)
            if not parsed_booked:
                raise HTTPException(status_code=400, detail="booked_move_date must be a valid date")
            lead.booked_move_date = parsed_booked
    if body.move_type is not None:
        lead.move_type = body.move_type.strip()
    if body.referral_source is not None:
        lead.referral_source = body.referral_source.strip() or None
    if body.estimated_total is not None:
        lead.estimated_total = _serialize_estimated_total(body.estimated_total)
    if body.payments is not None:
        if user.role not in ("admin", "sales_rep"):
            if any(payment.rep_paid or (payment.rep_paid_at or "").strip() for payment in body.payments):
                raise HTTPException(status_code=403, detail="Only admin and sales reps can mark rep payments")
        lead.payments = _serialize_payments(body.payments)

    primary_job = _get_or_create_primary_lead_job(lead, db)
    if next_company_id is not None:
        primary_job.company_id = lead.company_id

    if body.jobs is not None:
        requested_job_orders: dict[str, int] = {}
        incoming_job_ids: set[str] = set()

        for job_patch in body.jobs:
            job_payload = job_patch.dict(exclude_unset=True, by_alias=False)
            if not job_payload:
                continue

            target_job = primary_job
            target_job_id = (job_payload.get("id") or "").strip()
            if target_job_id:
                target_job = (
                    db.query(LeadJob)
                    .filter(LeadJob.id == target_job_id, LeadJob.lead_id == lead.id)
                    .first()
                )
                if not target_job:
                    raise HTTPException(status_code=404, detail=f"Job not found: {target_job_id}")
            else:
                # Upsert by SmartMoving job id when CRM job id is not available.
                # This keeps PATCH idempotent for import pipelines.
                target_smartmoving_job_id = (job_payload.get("smartmoving_job_id") or "").strip()
                if target_smartmoving_job_id:
                    existing_job = (
                        db.query(LeadJob)
                        .filter(
                            LeadJob.lead_id == lead.id,
                            LeadJob.smartmoving_job_id == target_smartmoving_job_id,
                        )
                        .first()
                    )
                    if existing_job:
                        target_job = existing_job
                    else:
                        target_job = LeadJob(
                            lead_id=lead.id,
                            company_id=lead.company_id,
                            # Always create at the tail first; requested sortOrder is applied in batch later.
                            job_order=_next_lead_job_order(lead.id, db),
                            smartmoving_job_id=target_smartmoving_job_id,
                            pickup_zip=primary_job.pickup_zip or "",
                            delivery_zip=primary_job.delivery_zip or "",
                            move_date=primary_job.move_date or "",
                            booked_move_date=primary_job.booked_move_date,
                            price=primary_job.price,
                        )
                        db.add(target_job)
                        db.flush()

            if not target_job.id:
                db.flush()
            incoming_job_ids.add(target_job.id)

            if "smartmoving_job_id" in job_payload:
                target_job.smartmoving_job_id = (job_payload.get("smartmoving_job_id") or "").strip() or None

            if "sort_order" in job_payload:
                next_sort_order = job_payload.get("sort_order")
                if next_sort_order is None:
                    raise HTTPException(status_code=400, detail="sortOrder cannot be null")
                try:
                    next_sort_order = int(next_sort_order)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="sortOrder must be an integer")
                if next_sort_order < 1:
                    raise HTTPException(status_code=400, detail="sortOrder must be >= 1")
                requested_job_orders[target_job.id] = next_sort_order

            if "pickup_zip" in job_payload:
                target_job.pickup_zip = (job_payload.get("pickup_zip") or "").strip()

            if "delivery_zip" in job_payload:
                target_job.delivery_zip = (job_payload.get("delivery_zip") or "").strip()

            current_pickup, current_stops, current_delivery = _read_job_route(db, target_job)
            next_pickup = current_pickup
            next_stops = current_stops
            next_delivery = current_delivery
            touch_route = any(
                key in job_payload
                for key in ("pickup_zip", "delivery_zip", "stops", "pickup_addresses", "delivery_addresses")
            )

            if "pickup_zip" in job_payload:
                next_pickup = _clean_optional_text(job_payload.get("pickup_zip") or "")
            if "delivery_zip" in job_payload:
                next_delivery = _clean_optional_text(job_payload.get("delivery_zip") or "")
            if "stops" in job_payload:
                next_stops = _normalize_stops_list(job_payload.get("stops") or [])

            if "pickup_addresses" in job_payload or "delivery_addresses" in job_payload:
                route = [
                    *_normalize_address_list(job_payload.get("pickup_addresses") or [], next_pickup),
                    *_normalize_address_list(job_payload.get("delivery_addresses") or [], next_delivery),
                ]
                if route:
                    next_pickup = route[0]
                    next_delivery = route[-1] if len(route) > 1 else ""
                    next_stops = route[1:-1] if len(route) > 2 else []

            if touch_route:
                if not next_pickup:
                    raise HTTPException(status_code=400, detail="At least one pickup address is required")
                if not next_delivery:
                    raise HTTPException(status_code=400, detail="At least one delivery address is required")
                target_job.pickup_zip = next_pickup
                target_job.delivery_zip = next_delivery
                _persist_job_route(db, target_job.id, next_pickup, next_stops, next_delivery)

            if "move_date" in job_payload:
                target_job.move_date = _normalize_move_date(job_payload.get("move_date") or "")

            if "booked_move_date" in job_payload:
                booked_raw = (job_payload.get("booked_move_date") or "").strip()
                if not booked_raw:
                    target_job.booked_move_date = None
                else:
                    booked = _parse_booked_move_date(booked_raw)
                    if not booked:
                        raise HTTPException(status_code=400, detail="booked_move_date must be a valid date")
                    target_job.booked_move_date = booked

            if "price" in job_payload:
                next_price = job_payload.get("price")
                if next_price is None:
                    target_job.price = None
                else:
                    try:
                        price_value = Decimal(str(next_price)).quantize(Decimal("0.01"))
                    except (InvalidOperation, ValueError):
                        raise HTTPException(status_code=400, detail="price must be a valid number")
                    if price_value < 0:
                        raise HTTPException(status_code=400, detail="price must be >= 0")
                    target_job.price = price_value

            if "estimated_charges" in job_payload:
                _replace_job_charges(target_job, job_payload.get("estimated_charges") or [], db)

        if requested_job_orders:
            desired_values = list(requested_job_orders.values())
            if len(set(desired_values)) != len(desired_values):
                raise HTTPException(status_code=400, detail="sortOrder values must be unique per lead")

            requested_ids = set(requested_job_orders.keys())
            desired_orders = set(desired_values)

            # Move untouched rows out of requested target slots.
            conflicting_rows = (
                db.query(LeadJob)
                .filter(
                    LeadJob.lead_id == lead.id,
                    LeadJob.job_order.in_(desired_orders),
                    ~LeadJob.id.in_(requested_ids),
                )
                .order_by(LeadJob.job_order.asc(), LeadJob.created_at.asc())
                .all()
            )

            next_tail_order = _next_lead_job_order(lead.id, db)
            for row in conflicting_rows:
                row.job_order = next_tail_order
                next_tail_order += 1

            # Two-phase assignment prevents collisions during swaps.
            requested_rows = (
                db.query(LeadJob)
                .filter(LeadJob.lead_id == lead.id, LeadJob.id.in_(requested_ids))
                .all()
            )

            temp_order = next_tail_order
            for row in requested_rows:
                row.job_order = temp_order
                temp_order += 1
            db.flush()

            for row in requested_rows:
                row.job_order = requested_job_orders[row.id]
            db.flush()

        # Mirror incoming jobs list exactly: delete every existing job not in payload.
        stale_jobs = (
            db.query(LeadJob)
            .filter(LeadJob.lead_id == lead.id, ~LeadJob.id.in_(incoming_job_ids))
            .all()
        )
        for stale_job in stale_jobs:
            db.delete(stale_job)
        if stale_jobs:
            db.flush()

        # Keep job_order contiguous for remaining jobs.
        remaining_jobs = (
            db.query(LeadJob)
            .filter(LeadJob.lead_id == lead.id)
            .order_by(LeadJob.job_order.asc(), LeadJob.created_at.asc())
            .all()
        )
        temp_order = _next_lead_job_order(lead.id, db)
        for row in remaining_jobs:
            row.job_order = temp_order
            temp_order += 1
        if remaining_jobs:
            db.flush()

        for index, row in enumerate(remaining_jobs, start=1):
            row.job_order = index
        if remaining_jobs:
            db.flush()

        # Keep lead-level move fields aligned with the current primary job.
        current_primary_job = (
            db.query(LeadJob)
            .filter(LeadJob.lead_id == lead.id)
            .order_by(LeadJob.job_order.asc(), LeadJob.created_at.asc())
            .first()
        ) or primary_job
        lead.move_date = current_primary_job.move_date
        lead.booked_move_date = current_primary_job.booked_move_date

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if "uq_lead_jobs_lead_order" in message or ("lead_id" in message and "job_order" in message):
            raise HTTPException(status_code=409, detail="Conflicting sortOrder values for this lead")
        raise HTTPException(status_code=500, detail="Failed to update lead")
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


@router.post("/leads/{lead_id}/refresh-smartmoving")
def refresh_lead_from_smartmoving(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    smartmoving_id = _clean_optional_text(lead.smartmoving_id)
    if not smartmoving_id:
        raise HTTPException(status_code=400, detail="Lead does not have a smartmoving_id")

    opportunity_result = get_opportunity(smartmoving_id)
    if opportunity_result.get("error"):
        error_text = str(opportunity_result.get("error") or "")
        lowered = error_text.lower()
        if "http 400" in lowered and "opportunity was not found" in lowered:
            resolved_lead_id = lead.id
            _hard_delete_lead(lead, db)
            return {
                "ok": True,
                "deleted_lead_id": resolved_lead_id,
                "reason": "smartmoving_opportunity_not_found",
            }
        raise HTTPException(status_code=502, detail=f"SmartMoving refresh failed: {opportunity_result['error']}")

    opportunity = opportunity_result.get("data")
    if not isinstance(opportunity, dict):
        raise HTTPException(status_code=502, detail="SmartMoving refresh returned an invalid payload")

    payload = _build_smartmoving_refresh_payload(opportunity, user)

    if isinstance(payload.get("payments"), list):
        existing_payments = _deserialize_payments(lead.payments)
        payload["payments"] = _merge_smartmoving_payments_with_existing(payload.get("payments") or [], existing_payments)

    audit_result = get_opportunity_audit_activity(smartmoving_id)
    if audit_result.get("error"):
        raise HTTPException(status_code=502, detail=f"SmartMoving audit failed: {audit_result['error']}")
    audit_rows = audit_result.get("data")
    if not isinstance(audit_rows, list):
        raise HTTPException(status_code=502, detail="SmartMoving audit returned an invalid payload")
    company = db.query(Company).filter(Company.id == lead.company_id).first()
    company_timezone = (company.timezone if company else "") or "America/New_York"

    last_booked_date = _last_booked_date_from_audit_rows(audit_rows, company_timezone)
    booked_iso = last_booked_date.isoformat() if last_booked_date is not None else ""
    payload["booked_move_date"] = booked_iso
    for job in payload.get("jobs") or []:
        if isinstance(job, dict):
            job["booked_move_date"] = booked_iso

    body = LeadUpdate.model_validate(payload)
    updated = update_lead(lead.id, body, user, db)
    created_links = _sync_smartmoving_document_links(lead, user, db)
    if isinstance(updated, dict):
        updated["smartmoving_document_links_synced"] = created_links
    return updated


def _send_rep_assignment_sms(lead: Lead, db: Session) -> None:
    if (lead.status or "").strip().lower() in NO_MESSAGE_STATUSES:
        return
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

ALLOWED_LEAD_STATUSES = {
    "new",
    "contacted",
    "quoted",
    "booked",
    "scheduled",
    "completed",
    "lost",
    "cancelled",
}


class NewLead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    full_name: str = ""
    email: str | None = None
    phone_number: str | None = None
    pickup_zip: str | None = None
    delivery_zip: str | None = None
    move_size: str | None = None
    volume: float | None = None
    weight: float | None = None
    move_date: str | None = None
    booked_move_date: str | None = None
    move_type: str | None = None
    created_time: str | None = None
    leadgen_id: str | None = None
    smartmoving_id: str | None = None
    smartmoving_job_id: str | None = None
    facebook_user_id: str | None = None
    notes: str | None = None
    referral_source: str | None = None
    service_type: str | None = None
    status: str | None = None
    assigned_to: str | None = None
    assigned_to_name: str | None = None
    sales_person_id: str | None = None
    sales_person_name: str | None = None
    estimated_charges: list[LeadJobChargePayload] = Field(default_factory=list, alias="estimatedCharges")
    estimated_total: EstimatedTotalPayload | None = Field(default=None, alias="estimatedTotal")
    payments: list[LeadPaymentPayload] = Field(default_factory=list)
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

    company = db.query(Company).filter(Company.name == body.company_name.strip()).first()
    if not company:
        raise HTTPException(status_code=400, detail=f"Company '{body.company_name}' not found")

    assigned_to_user_id = None
    assignment_mode = "manual"
    assignment_reason = "admin_available"

    requested_assignee_id = _clean_optional_text(body.assigned_to) or _clean_optional_text(body.sales_person_id)
    requested_assignee_name = _clean_optional_text(body.assigned_to_name) or _clean_optional_text(body.sales_person_name)

    if requested_assignee_id:
        assignee = db.query(User).filter(User.id == requested_assignee_id).first()
        if not assignee:
            raise HTTPException(status_code=400, detail="assigned_to user id not found")
        assigned_to_user_id = assignee.id
        assignment_reason = "api_assigned_to"
    elif requested_assignee_name:
        users = db.query(User).all()
        needle = _normalize_person_name(requested_assignee_name)
        matched_users = [u for u in users if _normalize_person_name(u.name) == needle]
        if not matched_users:
            available_names = sorted({(u.name or "").strip() for u in users if (u.name or "").strip()})
            preview = ", ".join(available_names[:10])
            extra = "" if len(available_names) <= 10 else f" (+{len(available_names) - 10} more)"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"sales_person_name '{requested_assignee_name}' not found"
                    + (f". Available reps: {preview}{extra}" if preview else "")
                ),
            )
        if len(matched_users) > 1:
            raise HTTPException(status_code=400, detail="sales_person_name is ambiguous; send assigned_to user id")
        assigned_to_user_id = matched_users[0].id
        assignment_reason = "api_assigned_to_name"

    # Auto-assign only while all admins are unavailable and no explicit assignee was provided.
    if not assigned_to_user_id and not _any_admin_available_now(db):
        available_rep_ids = _active_available_rep_ids(db)
        rep = _pick_round_robin_rep_for_company(company.id, db, available_rep_ids)
        if rep:
            assigned_to_user_id = rep.id
            assignment_mode = "auto"
            assignment_reason = "all_admins_unavailable_round_robin"
        else:
            assignment_mode = "queued"
            assignment_reason = "all_admins_unavailable_no_available_rep"

    raw_move_type = _clean_optional_text(body.move_type).lower()
    raw_status = _clean_optional_text(body.status).lower()
    status_provided = bool(raw_status)
    if raw_status and raw_status not in ALLOWED_LEAD_STATUSES:
        raw_status = "new"

    normalized_move_date = _normalize_move_date(_clean_optional_text(body.move_date))
    booked_raw = _clean_optional_text(body.booked_move_date)
    parsed_booked_date = _parse_booked_move_date(booked_raw)
    if booked_raw and not parsed_booked_date:
        raise HTTPException(status_code=400, detail="booked_move_date must be a valid date")

    volume_value = None
    if body.volume is not None:
        volume_value = _to_money_decimal(body.volume, "volume")
        if volume_value < 0:
            raise HTTPException(status_code=400, detail="volume must be >= 0")

    weight_value = None
    if body.weight is not None:
        weight_value = _to_money_decimal(body.weight, "weight")
        if weight_value < 0:
            raise HTTPException(status_code=400, detail="weight must be >= 0")

    lead = Lead(
        company_id=company.id,
        assigned_to=assigned_to_user_id,
        full_name=body.full_name.strip(),
        email=_clean_optional_text(body.email),
        phone=_normalize_phone(body.phone_number),
        source=body.source or "zapier",
        leadgen_id=_clean_optional_text(body.leadgen_id) or None,
        smartmoving_id=_clean_optional_text(body.smartmoving_id) or None,
        facebook_user_id=_clean_optional_text(body.facebook_user_id) or None,
        pickup_zip=_clean_optional_text(body.pickup_zip),
        delivery_zip=_clean_optional_text(body.delivery_zip),
        move_size=_clean_optional_text(body.move_size),
        volume=volume_value,
        weight=weight_value,
        move_date=normalized_move_date,
        booked_move_date=parsed_booked_date,
        move_type=MOVE_TYPE_MAP.get(raw_move_type, raw_move_type),
        created_time=_clean_optional_text(body.created_time),
        notes=_clean_optional_text(body.notes) or None,
        referral_source=_clean_optional_text(body.referral_source) or None,
        service_type=_clean_optional_text(body.service_type) or None,
        status=raw_status or "new",
        estimated_total=_serialize_estimated_total(body.estimated_total),
        payments=_serialize_payments(body.payments),
    )
    try:
        db.add(lead)
        db.flush()
        primary_job = LeadJob(
            lead_id=lead.id,
            company_id=lead.company_id,
            job_order=1,
            smartmoving_job_id=_clean_optional_text(body.smartmoving_job_id) or None,
            pickup_zip=lead.pickup_zip,
            delivery_zip=lead.delivery_zip,
            move_date=lead.move_date,
            booked_move_date=lead.booked_move_date,
            price=None,
        )
        db.add(primary_job)
        db.flush()
        if body.estimated_charges:
            _replace_job_charges(primary_job, body.estimated_charges, db)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        if "smartmoving_id" in str(e):
            raise HTTPException(status_code=409, detail=f"Lead with smartmoving_id '{body.smartmoving_id}' already exists")
        raise HTTPException(status_code=400, detail="Database integrity error")
    
    db.refresh(lead)
    logger.info("Created lead: %s (%s)", lead.full_name, lead.id)

    suppress_new_lead_automation = lead.status in NO_MESSAGE_STATUSES
    
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
    message = ""
    if not suppress_new_lead_automation and lead.phone and lead.smartmoving_id:
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

        if not suppress_new_lead_automation:
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
    if company.name == "Gorilla Haulers" and not status_provided and not suppress_new_lead_automation:
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
                delay_minutes=120,
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
