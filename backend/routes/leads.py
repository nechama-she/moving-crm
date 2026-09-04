import hashlib
import io
import json
import logging
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar
from urllib.parse import unquote, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from botocore.exceptions import ClientError
from dateutil import parser as date_parser
from fastapi import APIRouter, HTTPException, Query, Depends, Header, UploadFile, File, Request
from fastapi.responses import Response, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, cast, text, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from assignment_conflicts import find_assignment_conflicts
from assignment_webhook import send_assignment_webhook
from company_colors import resolve_company_color
from config import get_config
from database import get_db
from lead_audit import record_lead_update_log
from libs.common.phone import normalize_digits
from libs.common.ssm import get_ssm_cached
from libs.smartmoving.client import (
    begin_request_capture,
    check_opportunity_exists,
    create_provider_lead,
    download_opportunity_document,
    download_opportunity_file,
    get_opportunity,
    get_opportunity_job,
    get_opportunity_audit_activity,
    get_opportunity_documents,
    finish_request_capture,
    update_opportunity_salesperson,
)
from models import Lead, LeadUpdateLog, User, UserCompany, Company, OutreachEvent, AdminUnavailability, AdminUnavailabilityRep, RepAvailabilityWindow, AutoAssignEvent, LeadAttachment, DispatchCalendarDay, LeadJob, LeadJobCharge, Followup, SentMessage, Task, AppSetting, LeadDuplicationRule, MessageState, MissedCallState, CommunicationAssociation
from realtime import publish_realtime_event
from referral_assignment_rules import configured_rep_ids_for_referral
from routes.templates import get_company_template, render_template

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Leads"])
ModelT = TypeVar("ModelT", bound=BaseModel)

# Statuses that dispatch can see (booked and beyond)
DISPATCH_STATUSES = {"booked", "scheduled", "completed"}
SMARTMOVING_JOB_DETAIL_STATUSES = {"booked", "confirmed", "scheduled", "schedule"}
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
    """Keep CRM-managed payout fields when refreshing from SmartMoving."""
    merged: list[dict] = []
    for index, row in enumerate(smartmoving_rows):
        existing = existing_rows[index] if index < len(existing_rows) else {}
        rep_paid = bool(existing.get("repPaid") or False)
        rep_paid_at = str(existing.get("repPaidAt") or "").strip()

        next_row = dict(row)
        next_row["repPaid"] = rep_paid
        next_row["repPaidAt"] = rep_paid_at
        next_row["repCommissionPercent"] = existing.get("repCommissionPercent")
        next_row["repCommissionAmount"] = existing.get("repCommissionAmount")
        next_row["thirdPartyCommissionTo"] = str(existing.get("thirdPartyCommissionTo") or "").strip()
        next_row["thirdPartyCommissionAmount"] = float(existing.get("thirdPartyCommissionAmount") or 0)
        next_row["thirdPartyCommissionPaid"] = bool(existing.get("thirdPartyCommissionPaid") or False)
        next_row["thirdPartyCommissionPaidAt"] = str(existing.get("thirdPartyCommissionPaidAt") or "").strip()
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
        ("created_time", opportunity.get("createdAtUtc")),
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
    respect_availability: bool = True,
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

    if not respect_availability:
        return rep_rows
    active_ids = _filter_by_rep_availability([r.id for r in rep_rows], db, now=now)
    return [u for u in rep_rows if u.id in active_ids]


def _pick_round_robin_rep_for_company(
    company_id: str,
    db: Session,
    allowed_rep_ids: set[str] | None = None,
    now: datetime | None = None,
    respect_availability: bool = True,
) -> User | None:
    active_reps = _active_reps_for_company(
        company_id,
        db,
        allowed_rep_ids=allowed_rep_ids,
        now=now,
        respect_availability=respect_availability,
    )
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


LEAD_DUPLICATE_SCHEDULE_PREFIX = "lead-dup-"
LEAD_DUPLICATE_SCHEDULE_GROUP = "default"
LEAD_DUPLICATE_TIMEZONE = ZoneInfo("America/New_York")


def _move_duplication_into_business_hours(fire_at: datetime) -> datetime:
    """Keep automatic lead copies inside the 8 AM-8 PM Eastern window."""
    eastern = fire_at.astimezone(LEAD_DUPLICATE_TIMEZONE)
    if eastern.hour < 8:
        eastern = eastern.replace(hour=8, minute=0, second=0, microsecond=0)
    elif eastern.hour >= 20:
        eastern = (eastern + timedelta(days=1)).replace(
            hour=8,
            minute=0,
            second=0,
            microsecond=0,
        )
    return eastern.astimezone(timezone.utc)


def _enqueue_lead_for_duplication(
    lead_id: str,
    target_company_name: str,
    target_referral_source: str,
    delay_minutes: int,
) -> None:
    """Schedule a one-time EventBridge Scheduler invocation of the lead-duplicate Lambda.

    Uses EventBridge Scheduler (not SQS) because SQS DelaySeconds is capped at 15 minutes.
    The schedule auto-deletes after firing (ActionAfterCompletion=DELETE).
    """
    if os.getenv("ENABLE_LEAD_DUPLICATION", "false").strip().lower() != "true":
        logger.info("Lead duplication disabled; skipping schedule for lead %s", lead_id)
        return

    function_arn = os.getenv("LEAD_DUPLICATE_FUNCTION_ARN", "")
    role_arn = os.getenv("LEAD_DUPLICATE_SCHEDULER_ROLE_ARN", "")
    if not function_arn or not role_arn:
        logger.warning(
            "LEAD_DUPLICATE_FUNCTION_ARN or LEAD_DUPLICATE_SCHEDULER_ROLE_ARN not set; "
            "skipping schedule for lead %s",
            lead_id,
        )
        return

    fire_at = _utcnow() + timedelta(minutes=delay_minutes)
    fire_at = _move_duplication_into_business_hours(fire_at)
    # Scheduler expects naive UTC ISO8601 (no offset, no microseconds).
    schedule_at = fire_at.replace(microsecond=0, tzinfo=None).isoformat()

    # Schedule name must be unique and <=64 chars, [0-9A-Za-z_.-]
    short_id = lead_id.replace("-", "")[:24]
    epoch = int(fire_at.timestamp())
    # A lead may have several matching rules firing at the same time. Include the
    # destination in the name so every target gets its own schedule.
    destination_key = hashlib.sha256(
        f"{target_company_name}|{target_referral_source}".encode("utf-8")
    ).hexdigest()[:8]
    schedule_name = f"{LEAD_DUPLICATE_SCHEDULE_PREFIX}{short_id}-{epoch}-{destination_key}"

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


@router.get("/lead-duplications/pending")
def list_pending_lead_duplications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    scheduler = boto3.client("scheduler", region_name=os.getenv("AWS_REGION_NAME", "us-east-1"))
    schedules: list[dict] = []
    next_token = None
    try:
        while True:
            params = {
                "GroupName": LEAD_DUPLICATE_SCHEDULE_GROUP,
                "NamePrefix": LEAD_DUPLICATE_SCHEDULE_PREFIX,
                "State": "ENABLED",
                "MaxResults": 100,
            }
            if next_token:
                params["NextToken"] = next_token
            page = scheduler.list_schedules(**params)
            schedules.extend(page.get("Schedules") or [])
            next_token = page.get("NextToken")
            if not next_token:
                break
    except ClientError as exc:
        logger.exception("Failed to list pending lead duplication schedules")
        raise HTTPException(status_code=502, detail=f"Could not load pending duplications: {exc}")

    items: list[dict] = []
    for schedule in schedules:
        schedule_name = schedule.get("Name", "")
        try:
            detail = scheduler.get_schedule(
                GroupName=LEAD_DUPLICATE_SCHEDULE_GROUP,
                Name=schedule_name,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                continue
            logger.warning("Could not read lead duplication schedule %s: %s", schedule_name, exc)
            continue

        try:
            payload = json.loads((detail.get("Target") or {}).get("Input") or "{}")
        except (TypeError, ValueError):
            payload = {}

        lead_id = str(payload.get("lead_id") or "")
        lead = db.query(Lead).filter(Lead.id == lead_id).first() if lead_id else None
        company = db.query(Company).filter(Company.id == lead.company_id).first() if lead else None
        expression = detail.get("ScheduleExpression") or schedule.get("ScheduleExpression") or ""
        fire_at = expression[3:-1] + "Z" if expression.startswith("at(") and expression.endswith(")") else expression
        items.append({
            "schedule_name": schedule_name,
            "lead_id": lead_id,
            "lead_name": lead.full_name if lead else "",
            "smartmoving_id": lead.smartmoving_id if lead else "",
            "source_company_name": company.name if company else "",
            "target_company_name": payload.get("target_company_name") or "",
            "target_referral_source": payload.get("target_referral_source") or "",
            "fire_at": fire_at,
            "created_at": detail.get("CreationDate") or schedule.get("CreationDate"),
        })

    items.sort(key=lambda item: item["fire_at"])
    if os.getenv("ENABLE_LEAD_DUPLICATION", "false").strip().lower() != "true":
        sample_companies = db.query(Company).order_by(Company.name).limit(2).all()
        source_company = sample_companies[0].name if sample_companies else "Sample Moving Company"
        target_company = sample_companies[-1].name if sample_companies else "Destination Moving Company"
        items.insert(0, {
            "schedule_name": "__dev_sample_duplication__",
            "lead_id": "",
            "lead_name": "Sample Lead (Design Preview)",
            "smartmoving_id": "sample-smartmoving-id",
            "source_company_name": source_company,
            "target_company_name": target_company,
            "target_referral_source": f"Facebook-{target_company}-HHG",
            "fire_at": _move_duplication_into_business_hours(
                _utcnow() + timedelta(hours=8)
            ).isoformat(),
            "created_at": _utcnow().isoformat(),
            "is_sample": True,
        })
    return {"items": items, "total": len(items)}


@router.delete("/lead-duplications/pending/{schedule_name}")
def delete_pending_lead_duplication(
    schedule_name: str,
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if not schedule_name.startswith(LEAD_DUPLICATE_SCHEDULE_PREFIX):
        raise HTTPException(status_code=400, detail="Invalid lead duplication schedule")

    scheduler = boto3.client("scheduler", region_name=os.getenv("AWS_REGION_NAME", "us-east-1"))
    try:
        scheduler.delete_schedule(
            GroupName=LEAD_DUPLICATE_SCHEDULE_GROUP,
            Name=schedule_name,
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            raise HTTPException(status_code=404, detail="Pending duplication not found")
        logger.exception("Failed to delete lead duplication schedule %s", schedule_name)
        raise HTTPException(status_code=502, detail=f"Could not delete pending duplication: {exc}")

    logger.info("Admin %s deleted lead duplication schedule %s", user.id, schedule_name)
    return {"status": "deleted", "schedule_name": schedule_name}


class RunPendingDuplicationNowRequest(BaseModel):
    company_id: str
    referral_source: str


@router.post("/lead-duplications/pending/{schedule_name}/run-now")
def run_pending_lead_duplication_now(
    schedule_name: str,
    body: RunPendingDuplicationNowRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if not schedule_name.startswith(LEAD_DUPLICATE_SCHEDULE_PREFIX):
        raise HTTPException(status_code=400, detail="Invalid lead duplication schedule")

    company_id = _clean_optional_text(body.company_id)
    referral_source = _clean_optional_text(body.referral_source)
    if not referral_source:
        raise HTTPException(status_code=400, detail="Referral Source is required")
    allowed_company_ids = _get_user_company_ids(user, db)
    if company_id not in allowed_company_ids:
        raise HTTPException(status_code=403, detail="You do not have access to the selected company")
    target_company = db.query(Company).filter(Company.id == company_id).first()
    if not target_company:
        raise HTTPException(status_code=404, detail="Selected company not found")

    region = os.getenv("AWS_REGION_NAME", "us-east-1")
    scheduler = boto3.client("scheduler", region_name=region)
    try:
        schedule = scheduler.get_schedule(GroupName=LEAD_DUPLICATE_SCHEDULE_GROUP, Name=schedule_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            raise HTTPException(status_code=404, detail="Pending duplication not found")
        logger.exception("Failed to read lead duplication schedule %s", schedule_name)
        raise HTTPException(status_code=502, detail=f"Could not read pending duplication: {exc}")

    target = schedule.get("Target") or {}
    function_arn = _clean_optional_text(target.get("Arn"))
    try:
        payload = json.loads(target.get("Input") or "{}")
    except (TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Pending duplication has an invalid payload")
    if not function_arn or not isinstance(payload, dict) or not payload.get("lead_id"):
        raise HTTPException(status_code=502, detail="Pending duplication is incomplete")
    payload["target_company_name"] = target_company.name
    payload["target_referral_source"] = referral_source

    try:
        response = boto3.client("lambda", region_name=region).invoke(
            FunctionName=function_arn,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        if response.get("StatusCode") != 200:
            raise RuntimeError(f"Lambda returned status {response.get('StatusCode')}")
        raw_result = response.get("Payload").read().decode("utf-8") if response.get("Payload") else "{}"
        invocation_result = json.loads(raw_result or "{}")
        if response.get("FunctionError") or not invocation_result.get("ok"):
            error_message = invocation_result.get("errorMessage") or invocation_result.get("error") or raw_result
            raise RuntimeError(str(error_message)[:1500])
    except Exception as exc:
        logger.exception("Failed to invoke pending lead duplication %s", schedule_name)
        raise HTTPException(status_code=502, detail=f"Could not start duplication: {exc}")

    try:
        scheduler.delete_schedule(GroupName=LEAD_DUPLICATE_SCHEDULE_GROUP, Name=schedule_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            logger.exception("Duplication started but schedule %s could not be deleted", schedule_name)
            raise HTTPException(status_code=502, detail="Duplication started, but its pending schedule could not be removed")

    logger.info("Admin %s started duplication %s immediately", user.id, schedule_name)
    return {
        "status": "started",
        "schedule_name": schedule_name,
        "lead_id": payload.get("lead_id"),
        "target_company_name": target_company.name,
        "target_referral_source": referral_source,
        "result": invocation_result.get("result") or {},
    }


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


def _smartmoving_provider_key() -> str:
    return _clean_optional_text(get_ssm_cached("/meta-webhook/SMARTMOVING_PROVIDER_KEY"))


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
    if user.role in ("dispatch", "foreman"):
        raise HTTPException(status_code=403, detail=f"{user.role.title()} users are read-only")


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
    if user.role not in ("admin", "dispatch", "foreman"):
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
    rows_query = (
        db.query(LeadJob, Lead, Company.name.label("company_name"), Company.color.label("company_color"))
        .join(Lead, Lead.id == LeadJob.lead_id)
        .join(Company, Company.id == LeadJob.company_id)
        .filter(LeadJob.company_id.in_(target_company_ids))
        .filter(Lead.status.in_(DISPATCH_STATUSES))
    )
    if user.role == "foreman":
        rows_query = rows_query.filter(LeadJob.foreman_id == user.id)
    rows = rows_query.order_by(LeadJob.created_at.asc()).all()

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
                "foreman_id": job.foreman_id or "",
                "foreman_name": job.foreman.name if job.foreman else "",
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


@router.get("/sales-performance")
def get_sales_performance(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return 12 months of cumulative daily booked sales for each visible rep."""
    if user.role not in ("admin", "sales_rep", "dispatch"):
        raise HTTPException(status_code=403, detail="Sales performance access required")

    allowed_company_ids = _get_user_company_ids(user, db)
    if not allowed_company_ids:
        return {"months": [], "reps": []}

    local_today = datetime.now(ZoneInfo("America/New_York")).date()
    current_month = local_today.replace(day=1)
    months: list[date] = []
    cursor = current_month
    for _ in range(12):
        months.append(cursor)
        cursor = date(cursor.year - 1, 12, 1) if cursor.month == 1 else date(cursor.year, cursor.month - 1, 1)
    months.reverse()
    range_start = months[0]
    range_end = date(current_month.year + 1, 1, 1) if current_month.month == 12 else date(current_month.year, current_month.month + 1, 1)

    rows = (
        db.query(
            LeadJob.booked_move_date,
            Lead.estimated_total,
            User.id.label("assigned_to"),
            User.name.label("assigned_to_name"),
        )
        .join(Lead, Lead.id == LeadJob.lead_id)
        .join(User, User.id == Lead.assigned_to)
        .filter(LeadJob.company_id.in_(allowed_company_ids))
        .filter(LeadJob.job_order == 1)
        .filter(LeadJob.booked_move_date.isnot(None))
        .filter(LeadJob.booked_move_date >= range_start)
        .filter(LeadJob.booked_move_date < range_end)
        .filter(Lead.status.in_(DISPATCH_STATUSES))
    )
    if user.role in ("sales_rep", "dispatch"):
        rows = rows.filter(Lead.assigned_to == user.id)

    month_keys = [month.strftime("%Y-%m") for month in months]
    rep_totals: dict[str, dict[str, Any]] = {}
    for booked_date, estimated_total, assigned_to, assigned_to_name in rows.all():
        rep = rep_totals.setdefault(
            assigned_to,
            {
                "id": assigned_to,
                "name": assigned_to_name or "Unnamed salesperson",
                "months": {key: [0.0] * 31 for key in month_keys},
            },
        )
        total = _deserialize_estimated_total(estimated_total)
        amount = float((total or {}).get("finalTotal") or 0)
        rep["months"][booked_date.strftime("%Y-%m")][booked_date.day - 1] += amount

    reps = []
    for rep in rep_totals.values():
        series = []
        for month, key in zip(months, month_keys):
            running_total = 0.0
            cumulative = []
            next_month = date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)
            final_day = (next_month - timedelta(days=1)).day
            if month == current_month:
                final_day = local_today.day
            for day_index, daily_total in enumerate(rep["months"][key], start=1):
                running_total += daily_total
                cumulative.append(round(running_total, 2) if day_index <= final_day else None)
            series.append({
                "month": key,
                "label": month.strftime("%b %Y"),
                "values": cumulative,
                "total": round(running_total, 2),
            })
        reps.append({
            "id": rep["id"],
            "name": rep["name"],
            "series": series,
        })

    reps.sort(key=lambda rep: rep["name"].lower())
    return {
        "months": [{"month": key, "label": month.strftime("%b %Y")} for month, key in zip(months, month_keys)],
        "reps": reps,
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
    if user.role not in ("admin", "dispatch", "sales_rep", "foreman"):
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
        if user.role == "foreman" and job.foreman_id != user.id:
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
    elif user.role == "foreman":
        rows = [(job, lead, company_name, company_color) for job, lead, company_name, company_color in rows if job.foreman_id == user.id]

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
    if company_id:
        if company_id not in company_ids:
            return {"items": [], "total": 0, "has_more": False}
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


@router.get("/leads/aircall-rep")
def get_assigned_rep_aircall_id(
    client_phone: str = Query(...),
    company_phone: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resolve an assigned rep's Aircall number from client and company phones."""
    client_phone = _normalize_phone(client_phone)
    company_phone = _normalize_phone(company_phone)
    if not client_phone or not company_phone:
        raise HTTPException(
            status_code=400,
            detail="client_phone and company_phone must contain digits",
        )

    company_ids = set(_get_user_company_ids(user, db))
    companies = [
        company
        for company in db.query(Company).all()
        if company.id in company_ids and _normalize_phone(company.phone) == company_phone
    ]
    if not companies:
        raise HTTPException(status_code=404, detail="Company not found")
    if len(companies) > 1:
        raise HTTPException(status_code=409, detail="Company phone matches multiple companies")

    matching_leads = [
        lead
        for lead in db.query(Lead).filter(Lead.company_id == companies[0].id).all()
        if _normalize_phone(lead.phone) == client_phone
    ]
    if not matching_leads:
        raise HTTPException(status_code=404, detail="Lead not found")

    # A client can submit more than once. Route calls using the latest CRM record.
    lead = max(
        matching_leads,
        key=lambda row: (
            (row.updated_at or row.created_at or datetime.min).isoformat(),
            row.id or "",
        ),
    )
    if not lead.assigned_to:
        raise HTTPException(status_code=404, detail="Lead has no assigned rep")

    rep = db.query(User).filter(User.id == lead.assigned_to).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Assigned rep not found")
    if not (rep.aircall_number_id or "").strip():
        raise HTTPException(status_code=404, detail="Assigned rep has no Aircall number ID")

    return {"aircall_number_id": rep.aircall_number_id.strip()}


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
    if user.role == "foreman" and not db.query(LeadJob.id).filter(
        LeadJob.lead_id == lead.id,
        LeadJob.foreman_id == user.id,
    ).first():
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
    if user.role == "foreman" and not db.query(LeadJob.id).filter(
        LeadJob.lead_id == lead.id,
        LeadJob.foreman_id == user.id,
    ).first():
        raise HTTPException(status_code=404, detail="Lead not found")

    # If facebook_user_id is missing, try to find it from sender_info
    if user.role != "foreman" and not lead.facebook_user_id:
        sender_id = _lookup_sender_id(lead)
        if sender_id:
            lead.facebook_user_id = sender_id
            db.commit()
            logger.info("Matched sender_id %s for lead %s", sender_id, lead.id)

    return lead.to_dict()


class CopyLeadRequest(BaseModel):
    company_id: str
    referral_source: str = ""
    assigned_to: str = ""


@router.get("/leads/{lead_id}/copy-conflicts")
def copy_lead_conflicts(
    lead_id: str,
    assigned_to: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can check copy conflicts")
    source_lead = _get_visible_lead_or_404(lead_id, user, db)
    rep = db.query(User).filter(User.id == assigned_to).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Selected rep not found")

    conditions = []
    normalized_name = (source_lead.full_name or "").strip().lower()
    normalized_email = (source_lead.email or "").strip().lower()
    normalized_phone = normalize_digits(source_lead.phone or "")[-10:]
    if normalized_name:
        conditions.append(func.lower(func.trim(Lead.full_name)) == normalized_name)
    if normalized_email:
        conditions.append(func.lower(func.trim(Lead.email)) == normalized_email)
    if normalized_phone:
        conditions.append(func.right(func.regexp_replace(Lead.phone, r"\D", "", "g"), 10) == normalized_phone)
    matches = (
        db.query(Lead)
        .options(joinedload(Lead.company))
        .filter(Lead.assigned_to == rep.id, or_(*conditions))
        .order_by(Lead.created_at.desc())
        .limit(50)
        .all()
        if conditions else []
    )
    items = []
    for match in matches:
        fields = []
        if normalized_name and (match.full_name or "").strip().lower() == normalized_name:
            fields.append("name")
        if normalized_email and (match.email or "").strip().lower() == normalized_email:
            fields.append("email")
        if normalized_phone and normalize_digits(match.phone or "")[-10:] == normalized_phone:
            fields.append("phone")
        items.append({
            "id": match.id,
            "name": match.full_name or "",
            "phone": match.phone or "",
            "email": match.email or "",
            "company": match.company.name if match.company else "",
            "smartmoving_id": match.smartmoving_id or "",
            "matched_fields": fields,
        })
    return {"rep": {"id": rep.id, "name": rep.name}, "items": items}


def create_lead_through_copy_path(
    *,
    db: Session,
    target_company: Company,
    full_name: str,
    phone: str = "",
    email: str = "",
    pickup_zip: str = "",
    delivery_zip: str = "",
    move_date: str = "",
    move_size: str = "",
    referral_source: str = "",
    notes: str = "",
    facebook_user_id: str = "",
    assigned_to: str = "",
) -> tuple[Lead, dict]:
    """Create in SmartMoving, then use the canonical CRM lead-creation path."""
    branch_id = _clean_optional_text(target_company.samrtmoving_branch_id)
    provider_key = _smartmoving_provider_key()
    if not branch_id:
        raise HTTPException(status_code=400, detail=f"{target_company.name} does not have a SmartMoving branch ID configured")
    if not provider_key:
        raise HTTPException(status_code=500, detail="SmartMoving lead-copy provider is not configured")

    resolved_referral_source = _clean_optional_text(referral_source) or f"Facebook-{target_company.name}-HHG"
    smartmoving_payload = {
        "fullName": full_name,
        "phoneNumber": phone,
        "email": email,
        "originZip": pickup_zip,
        "destinationZip": delivery_zip,
        "moveDate": move_date,
        "notes": notes,
        "referralSource": resolved_referral_source,
        "serviceType": "Moving",
        "moveSize": move_size or "Room or Less",
    }
    smartmoving_result = create_provider_lead(provider_key, branch_id, smartmoving_payload)
    if not smartmoving_result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=f"SmartMoving could not create the copied lead: {smartmoving_result.get('error', 'unknown error')}",
        )

    api_secret = get_config().get("API_SECRET", os.getenv("API_SECRET", ""))
    creation_result = create_lead(
        NewLead(
            full_name=full_name,
            email=email,
            phone_number=phone,
            pickup_zip=pickup_zip,
            delivery_zip=delivery_zip,
            move_size=move_size,
            move_date=move_date,
            smartmoving_id=_clean_optional_text(smartmoving_result.get("lead_id")) or None,
            facebook_user_id=facebook_user_id or None,
            assigned_to=assigned_to or None,
            notes=notes,
            referral_source=resolved_referral_source,
            service_type="Moving",
            status="new",
            company_name=target_company.name,
            source="Facebook",
        ),
        x_api_secret=api_secret,
        db=db,
    )
    created_lead = db.query(Lead).filter(Lead.id == creation_result["lead_id"]).first()
    if not created_lead:
        raise HTTPException(status_code=500, detail="Lead was created but could not be reloaded")
    assignment_result: dict = {"attempted": False, "ok": True}
    if assigned_to:
        assignment_result = {"attempted": True, "ok": False}
        assigned_rep = db.query(User).filter(User.id == assigned_to).first()
        smartmoving_lead_id = _clean_optional_text(smartmoving_result.get("lead_id"))
        if not assigned_rep:
            assignment_result["error"] = "Selected CRM rep was not found"
        else:
            assignment_result["ok"] = True
            assignment_result["rep_name"] = assigned_rep.name
            assignment_result["smartmoving"] = {
                "attempted": bool(
                    _clean_optional_text(created_lead.smartmoving_id)
                    and _clean_optional_text(assigned_rep.smartmoving_rep_id)
                ),
                **_sync_assignment_to_smartmoving(created_lead, assigned_rep),
            }
            assignment_result["webhook"] = send_assignment_webhook(created_lead, assigned_rep)
            if not _clean_optional_text(assigned_rep.phone):
                assignment_result["notification"] = {
                    "attempted": False,
                    "ok": False,
                    "error": f"{assigned_rep.name} does not have a phone number configured",
                }
            elif not _clean_optional_text(target_company.aircall_number_id):
                assignment_result["notification"] = {
                    "attempted": False,
                    "ok": False,
                    "error": f"{target_company.name} does not have an Aircall number ID configured",
                }
            else:
                from libs.aircall import send_sms

                smartmoving_url = f"https://app.smartmoving.com/opportunities/{smartmoving_lead_id}/sales"
                notification_message = (
                    f"You have been assigned a new lead: {full_name}. "
                    f"Open it in SmartMoving: {smartmoving_url}"
                )
                notification_result = send_sms(
                    to=assigned_rep.phone,
                    text=notification_message,
                    number_id=_clean_optional_text(target_company.aircall_number_id),
                )
                assignment_result["notification"] = {
                    "attempted": True,
                    **notification_result,
                }
    creation_result["rep_assignment"] = assignment_result
    return created_lead, creation_result


@router.post("/leads/{lead_id}/copy")
def copy_lead(
    lead_id: str,
    body: CopyLeadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can copy leads")
    source_lead = _get_visible_lead_or_404(lead_id, user, db)

    allowed_company_ids = _get_user_company_ids(user, db)
    target_company_id = _clean_optional_text(body.company_id)
    if target_company_id not in allowed_company_ids:
        raise HTTPException(status_code=403, detail="You do not have access to the selected company")

    target_company = db.query(Company).filter(Company.id == target_company_id).first()
    if not target_company:
        raise HTTPException(status_code=404, detail="Selected company not found")
    matching_company_ids = [
        row.id
        for row in db.query(Company.id).filter(Company.name == target_company.name).all()
    ]
    if matching_company_ids != [target_company.id]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot copy lead: company name '{target_company.name}' is not unique. "
                "The lead was not created or messaged."
            ),
        )
    referral_source = _clean_optional_text(body.referral_source) or f"Facebook-{target_company.name}-HHG"
    copied_lead, creation_result = create_lead_through_copy_path(
        db=db,
        target_company=target_company,
        full_name=source_lead.full_name or "",
        phone=source_lead.phone or "",
        email=source_lead.email or "",
        pickup_zip=source_lead.pickup_zip or "",
        delivery_zip=source_lead.delivery_zip or "",
        move_date=source_lead.move_date or "",
        move_size=source_lead.move_size or "",
        referral_source=referral_source,
        notes="",
        assigned_to=_clean_optional_text(body.assigned_to),
    )

    return {
        "ok": True,
        "lead": copied_lead.to_dict(),
        "source_lead_id": source_lead.id,
        "creation": creation_result,
    }


@router.get("/leads/{lead_id}/logs")
def get_lead_update_logs(
    lead_id: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "sales_rep"):
        raise HTTPException(status_code=403, detail="Lead logs are not available for this role")
    _get_visible_lead_or_404(lead_id, user, db)
    query = db.query(LeadUpdateLog).filter(LeadUpdateLog.lead_id == lead_id)
    total = query.count()
    rows = (
        query
        .order_by(LeadUpdateLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [row.to_dict() for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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


class ValidateSmartMovingLeadsRequest(BaseModel):
    lead_ids: list[str] = Field(default_factory=list, max_length=100)


@router.post("/leads/validate-smartmoving")
def validate_smartmoving_leads(
    body: ValidateSmartMovingLeadsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually validate queue leads and delete only confirmed SmartMoving misses."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can validate Sales Work Queue leads")
    requested_ids = list(dict.fromkeys(value.strip() for value in body.lead_ids if value.strip()))
    if not requested_ids:
        return {"ok": True, "checked": 0, "removed_lead_ids": [], "skipped": [], "errors": []}

    company_ids = _get_user_company_ids(user, db)
    leads = db.query(Lead).filter(Lead.id.in_(requested_ids), Lead.company_id.in_(company_ids)).all()
    checkable = {lead.id: (lead.smartmoving_id or "").strip() for lead in leads if (lead.smartmoving_id or "").strip()}
    skipped = [lead.id for lead in leads if not (lead.smartmoving_id or "").strip()]
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(checkable)))) as executor:
        futures = {
            executor.submit(check_opportunity_exists, smartmoving_id): lead_id
            for lead_id, smartmoving_id in checkable.items()
        }
        for future in as_completed(futures):
            lead_id = futures[future]
            try:
                results[lead_id] = future.result()
            except Exception as exc:
                results[lead_id] = {"ok": False, "error": str(exc)}

    removed = []
    updated_created_times = []
    updated_statuses = []
    errors = []
    leads_by_id = {lead.id: lead for lead in leads}
    for lead_id, result in results.items():
        if not result.get("ok"):
            errors.append({"lead_id": lead_id, "error": result.get("error", "SmartMoving check failed")})
            continue
        if result.get("exists") is False:
            _hard_delete_lead(leads_by_id[lead_id], db)
            removed.append(lead_id)
            continue
        created_at_utc = _clean_optional_text(result.get("created_at_utc"))
        if created_at_utc:
            leads_by_id[lead_id].created_time = created_at_utc
            updated_created_times.append(lead_id)
        smartmoving_status = _map_smartmoving_status(result.get("status"))
        if smartmoving_status:
            leads_by_id[lead_id].status = smartmoving_status
            updated_statuses.append(lead_id)

    if updated_created_times or updated_statuses:
        db.commit()

    return {
        "ok": not errors,
        "checked": len(checkable),
        "removed_lead_ids": removed,
        "updated_created_time_lead_ids": updated_created_times,
        "updated_status_lead_ids": updated_statuses,
        "skipped": skipped,
        "errors": errors,
    }


def _hard_delete_lead(lead: Lead, db: Session) -> None:
    smartmoving_id = (lead.smartmoving_id or "").strip()
    resolved_lead_id = lead.id
    s3_urls_to_delete: list[str] = []

    try:
        job_ids = [
            row[0]
            for row in db.query(LeadJob.id).filter(LeadJob.lead_id == resolved_lead_id).all()
            if row and row[0]
        ]
        if job_ids:
            db.query(LeadJobCharge).filter(LeadJobCharge.job_id.in_(job_ids)).delete(synchronize_session=False)

        s3_urls_to_delete = [
            attachment.external_url or ""
            for attachment in db.query(LeadAttachment).filter(LeadAttachment.lead_id == resolved_lead_id).all()
            if (attachment.external_source or "").strip().lower().endswith("_s3")
        ]
        db.query(LeadAttachment).filter(LeadAttachment.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(LeadJob).filter(LeadJob.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(Task).filter(Task.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(AutoAssignEvent).filter(AutoAssignEvent.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(OutreachEvent).filter(OutreachEvent.lead_id == resolved_lead_id).delete(synchronize_session=False)
        db.query(MessageState).filter(MessageState.lead_id == resolved_lead_id).update(
            {MessageState.lead_id: None}, synchronize_session=False
        )
        db.query(MissedCallState).filter(MissedCallState.lead_id == resolved_lead_id).update(
            {MissedCallState.lead_id: None}, synchronize_session=False
        )
        db.query(CommunicationAssociation).filter(
            CommunicationAssociation.lead_id == resolved_lead_id
        ).delete(synchronize_session=False)

        if smartmoving_id:
            db.query(Followup).filter(Followup.smartmoving_id == smartmoving_id).delete(synchronize_session=False)
            db.query(SentMessage).filter(SentMessage.smartmoving_id == smartmoving_id).delete(synchronize_session=False)
            db.query(OutreachEvent).filter(OutreachEvent.smartmoving_id == smartmoving_id).delete(synchronize_session=False)

        db.delete(lead)
        db.commit()
        for external_url in s3_urls_to_delete:
            try:
                _delete_s3_url(external_url)
            except Exception:
                logger.exception("Failed cleaning S3 file after deleting lead %s", resolved_lead_id)
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
    if user.role == "foreman":
        assigned_job = db.query(LeadJob.id).filter(
            LeadJob.lead_id == lead.id,
            LeadJob.foreman_id == user.id,
        ).first()
        if not assigned_job:
            raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def _get_visible_lead_by_smartmoving_or_404(smartmoving_id: str, user: User, db: Session) -> Lead:
    company_ids = _get_user_company_ids(user, db)
    lead = (
        db.query(Lead)
        .filter(Lead.smartmoving_id == smartmoving_id, Lead.company_id.in_(company_ids))
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if user.role == "foreman" and not db.query(LeadJob.id).filter(
        LeadJob.lead_id == lead.id,
        LeadJob.foreman_id == user.id,
    ).first():
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


class ExternalLeadUpdateLogRequest(BaseModel):
    method: str = "POST"
    url: str = ""
    headers: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] | list[Any] | None = None


class ExternalLeadUpdateLogResponse(BaseModel):
    status_code: int | None = None
    body: dict[str, Any] | list[Any] | None = None


class ExternalLeadUpdateLog(BaseModel):
    request: ExternalLeadUpdateLogRequest | None = None
    response: ExternalLeadUpdateLogResponse | None = None


class LeadJobChargesBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    estimated_charges: list[LeadJobChargePayload] = Field(default_factory=list, alias="estimatedCharges")
    logs: list[ExternalLeadUpdateLog] | None = None


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
    rep_commission_percent: float | None = Field(default=None, alias="repCommissionPercent")
    rep_commission_amount: float | None = Field(default=None, alias="repCommissionAmount")
    third_party_commission_to: str = Field(default="", alias="thirdPartyCommissionTo")
    third_party_commission_amount: float = Field(default=0, alias="thirdPartyCommissionAmount")
    third_party_commission_paid: bool = Field(default=False, alias="thirdPartyCommissionPaid")
    third_party_commission_paid_at: str = Field(default="", alias="thirdPartyCommissionPaidAt")


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
            "repCommissionPercent": payment.rep_commission_percent,
            "repCommissionAmount": payment.rep_commission_amount,
            "thirdPartyCommissionTo": (payment.third_party_commission_to or "").strip(),
            "thirdPartyCommissionAmount": float(payment.third_party_commission_amount),
            "thirdPartyCommissionPaid": bool(payment.third_party_commission_paid),
            "thirdPartyCommissionPaidAt": (payment.third_party_commission_paid_at or "").strip(),
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
            "repCommissionPercent": float(row["repCommissionPercent"]) if row.get("repCommissionPercent") is not None else None,
            "repCommissionAmount": float(row["repCommissionAmount"]) if row.get("repCommissionAmount") is not None else None,
            "thirdPartyCommissionTo": str(row.get("thirdPartyCommissionTo") or "").strip(),
            "thirdPartyCommissionAmount": float(row.get("thirdPartyCommissionAmount") or 0),
            "thirdPartyCommissionPaid": bool(row.get("thirdPartyCommissionPaid") or False),
            "thirdPartyCommissionPaidAt": str(row.get("thirdPartyCommissionPaidAt") or "").strip(),
        })
    return payments


def _merge_partial_models(
    updates: list[ModelT],
    existing_rows: list[dict[str, object]],
) -> list[ModelT]:
    """Apply only explicitly submitted model fields; preserve every omitted value."""
    return [
        type(update).model_validate({
            **(existing_rows[index] if index < len(existing_rows) else {}),
            **update.model_dump(by_alias=True, exclude_unset=True),
        })
        for index, update in enumerate(updates)
    ]


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
    notes: str = ""
    customer_notes: str = ""
    foreman_notes: str = ""
    logs: list[ExternalLeadUpdateLog] | None = None


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
    foreman_id: str | None = None
    notes: str | None = None
    customer_notes: str | None = None
    foreman_notes: str | None = None
    logs: list[ExternalLeadUpdateLog] | None = None


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


def _validate_job_route_has_one_side(pickup: str, delivery: str) -> None:
    if not pickup and not delivery:
        raise HTTPException(status_code=400, detail="At least one pickup or delivery address is required")


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
    if user.role != "foreman":
        _get_or_create_primary_lead_job(lead, db)
        db.commit()

    rows_query = (
        db.query(LeadJob)
        .filter(LeadJob.lead_id == lead.id)
    )
    if user.role == "foreman":
        rows_query = rows_query.filter(LeadJob.foreman_id == user.id)
    rows = rows_query.order_by(LeadJob.job_order.asc(), LeadJob.created_at.asc()).all()
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
        notes=(body.notes or "").strip() or None,
        customer_notes=(body.customer_notes or "").strip() or None,
        foreman_notes=(body.foreman_notes or "").strip() or None,
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

    _validate_job_route_has_one_side(pickup, delivery)
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
    payload = body.model_dump(exclude_unset=True, by_alias=False)
    if user.role == "foreman" and set(payload) != {"foreman_notes"}:
        raise HTTPException(status_code=403, detail="Foreman users can only update foreman notes")
    if user.role == "dispatch" and (not payload or not set(payload).issubset({"foreman_id", "notes", "customer_notes", "foreman_notes"})):
        raise HTTPException(status_code=403, detail="Dispatch users can only assign a foreman or update job notes")
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadJob)
        .filter(LeadJob.id == job_id, LeadJob.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.role == "foreman" and row.foreman_id != user.id:
        raise HTTPException(status_code=403, detail="This job is not assigned to you")

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

    if "foreman_id" in payload:
        if user.role not in ("admin", "dispatch"):
            raise HTTPException(status_code=403, detail="Only admin or dispatch can assign a foreman")
        next_foreman_id = (payload.get("foreman_id") or "").strip()
        if not next_foreman_id:
            row.foreman_id = None
        else:
            foreman = db.query(User).filter(User.id == next_foreman_id, User.role == "foreman").first()
            if not foreman:
                raise HTTPException(status_code=404, detail="Foreman not found")
            if user.role == "dispatch" and foreman.manager_dispatch_id != user.id:
                raise HTTPException(status_code=403, detail="You can only assign your own foremen")
            foreman_company = db.query(UserCompany).filter(
                UserCompany.user_id == foreman.id,
                UserCompany.company_id == row.company_id,
            ).first()
            if not foreman_company:
                raise HTTPException(status_code=400, detail="Foreman is not assigned to this job's company")
            row.foreman_id = foreman.id

    if "notes" in payload:
        row.notes = (payload.get("notes") or "").strip() or None
    if "customer_notes" in payload:
        row.customer_notes = (payload.get("customer_notes") or "").strip() or None
    if "foreman_notes" in payload:
        row.foreman_notes = (payload.get("foreman_notes") or "").strip() or None

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

    _validate_job_route_has_one_side(next_pickup, next_delivery)

    row.pickup_zip = next_pickup
    row.delivery_zip = next_delivery
    if "move_date" in payload:
        row.move_date = _normalize_move_date(payload.get("move_date") or "")

    if "booked_move_date" in payload:
        booked_raw = (payload.get("booked_move_date") or "").strip()
        if booked_raw:
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


class AttachmentMoveBody(BaseModel):
    job_id: str | None = None


class AttachmentDownloadBody(BaseModel):
    attachment_ids: list[str] | None = None


def _get_job_or_404(lead_id: str, job_id: str, user: User, db: Session) -> "LeadJob":
    lead = _get_visible_lead_or_404(lead_id, user, db)
    job = (
        db.query(LeadJob)
        .filter(LeadJob.id == job_id, LeadJob.lead_id == lead.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.role == "foreman" and job.foreman_id != user.id:
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


def _safe_attachment_name(value: str) -> str:
    return re.sub(r'[\\/\r\n"]+', "_", (value or "").strip())[:255] or "attachment"


def _upload_attachment_bytes_to_s3(
    lead_id: str,
    job_id: str | None,
    file_name: str,
    content: bytes,
    content_type: str,
    source: str,
) -> str:
    bucket = (os.getenv("ATTACHMENTS_BUCKET") or "").strip()
    if not bucket:
        raise HTTPException(status_code=500, detail="Attachment storage is not configured")
    safe_name = _safe_attachment_name(file_name)
    job_path = job_id or "lead"
    object_key = f"leads/{lead_id}/jobs/{job_path}/{source}/{uuid4()}/{safe_name}"
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=object_key,
        Body=content,
        ContentType=content_type or "application/octet-stream",
        ServerSideEncryption="AES256",
    )
    return f"s3://{bucket}/{object_key}"


def _migrate_stored_attachment_blobs_to_s3(lead_id: str, db: Session) -> int:
    """Move legacy database-backed attachments to S3 without changing their IDs."""
    rows = (
        db.query(LeadAttachment)
        .filter(
            LeadAttachment.lead_id == lead_id,
            LeadAttachment.is_external_link.is_(False),
        )
        .all()
    )
    migrated = 0
    uploaded_urls: list[str] = []
    for row in rows:
        content = bytes(row.file_blob or b"")
        if not content:
            continue
        try:
            row.external_url = _upload_attachment_bytes_to_s3(
                lead_id=row.lead_id,
                job_id=row.job_id,
                file_name=row.file_name,
                content=content,
                content_type=row.content_type,
                source="crm",
            )
            uploaded_urls.append(row.external_url)
            row.is_external_link = True
            row.external_source = "crm_s3"
            row.file_blob = b""
            migrated += 1
        except Exception:
            logger.exception("Failed migrating attachment %s to S3", row.id)
    if migrated:
        try:
            db.commit()
        except Exception:
            db.rollback()
            for external_url in uploaded_urls:
                try:
                    _delete_s3_url(external_url)
                except Exception:
                    logger.exception("Failed cleaning orphaned migrated attachment %s", external_url)
            raise
    return migrated


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


def _extract_opportunity_files(payload: object) -> list[dict[str, str]]:
    """Extract the URL strings returned in SmartMoving opportunityFiles arrays."""
    extracted: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def walk(node: object, smartmoving_job_id: str = "") -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, smartmoving_job_id)
            return
        if not isinstance(node, dict):
            return

        nested_job_id = _clean_optional_text(
            node.get("smartmovingJobId")
            or node.get("opportunityJobId")
            or node.get("jobId")
        ) or smartmoving_job_id
        for key, value in node.items():
            if str(key).lower() == "opportunityfiles" and isinstance(value, list):
                for raw_url in value:
                    url = _clean_optional_text(raw_url)
                    if not url or url in seen_urls:
                        continue
                    parsed = urlparse(url)
                    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "smfilestore.blob.core.windows.net":
                        continue
                    seen_urls.add(url)
                    file_name = re.sub(
                        r'[\\/\r\n"]+',
                        "_",
                        unquote(parsed.path.rsplit("/", 1)[-1]).strip(),
                    ) or "SmartMoving File"
                    extracted.append({
                        "url": url,
                        "name": file_name,
                        "smartmoving_job_id": nested_job_id,
                    })
            else:
                walk(value, nested_job_id)

    walk(payload)
    return extracted


def _sync_opportunity_files_to_s3(
    lead: Lead,
    opportunity: dict,
    user: User,
    db: Session,
) -> int:
    bucket = (os.getenv("ATTACHMENTS_BUCKET") or "").strip()
    files = _extract_opportunity_files(opportunity)
    if not bucket or not files:
        if files and not bucket:
            logger.warning("Skipping SmartMoving opportunityFiles: ATTACHMENTS_BUCKET is not configured")
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

    job_by_smartmoving_id = {
        (job.smartmoving_job_id or "").strip(): job
        for job in jobs
        if (job.smartmoving_job_id or "").strip()
    }
    existing_by_hash = {
        (row.source_external_id or "").strip(): row
        for row in db.query(LeadAttachment)
        .filter(
            LeadAttachment.lead_id == lead.id,
            LeadAttachment.external_source == "smartmoving_s3",
        )
        .all()
        if (row.source_external_id or "").strip()
    }

    s3 = boto3.client("s3")
    created = 0
    reassigned = 0
    uploaded_keys: list[str] = []
    for item in files:
        source_hash = hashlib.sha256(item["url"].encode("utf-8")).hexdigest()
        target_job = job_by_smartmoving_id.get((item.get("smartmoving_job_id") or "").strip())
        target_job_id = target_job.id if target_job else None
        existing_row = existing_by_hash.get(source_hash)
        if source_hash in existing_by_hash:
            if existing_row and existing_row.job_id != target_job_id:
                existing_row.job_id = target_job_id
                reassigned += 1
            continue
        fetched = download_opportunity_file(item["url"])
        if not fetched.get("ok"):
            logger.warning("Could not download SmartMoving opportunity file %s: %s", item["url"], fetched.get("error"))
            continue
        content = fetched.get("content") or b""
        if not content or len(content) > MAX_ATTACHMENT_SIZE_BYTES:
            logger.warning("Skipping SmartMoving opportunity file with invalid size: %s", item["url"])
            continue

        file_name = re.sub(
            r'[\\/\r\n"]+',
            "_",
            _clean_optional_text(fetched.get("file_name")) or item["name"],
        )[:255]
        content_type = _clean_optional_text(fetched.get("content_type")) or "application/octet-stream"
        file_scope = f"jobs/{target_job.id}" if target_job else "lead"
        object_key = f"leads/{lead.id}/{file_scope}/smartmoving/{source_hash}/{file_name}"
        try:
            s3.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
            uploaded_keys.append(object_key)
        except Exception:
            logger.exception("Failed uploading SmartMoving opportunity file to S3: %s", item["url"])
            continue

        db.add(LeadAttachment(
            lead_id=lead.id,
            job_id=target_job_id,
            file_name=file_name,
            content_type=content_type,
            file_size=len(content),
            file_blob=b"",
            external_url=f"s3://{bucket}/{object_key}",
            is_external_link=True,
            external_source="smartmoving_s3",
            source_external_id=source_hash,
            uploaded_by=user.id,
        ))
        existing_by_hash[source_hash] = None
        created += 1

    if created or reassigned:
        try:
            db.commit()
        except Exception:
            db.rollback()
            for object_key in uploaded_keys:
                try:
                    s3.delete_object(Bucket=bucket, Key=object_key)
                except Exception:
                    logger.exception("Failed cleaning orphaned S3 attachment %s", object_key)
            logger.exception("Failed saving SmartMoving S3 attachment rows for lead %s", lead.id)
            return 0
    return created


def _sync_smartmoving_documents_to_s3(lead: Lead, user: User, db: Session) -> int:
    """Download SmartMoving documents into S3 and upsert their attachment rows."""
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

    job_by_smartmoving_id = {
        (row.smartmoving_job_id or "").strip(): row
        for row in jobs
        if (row.smartmoving_job_id or "").strip()
    }

    existing_rows = db.query(LeadAttachment).filter(
        LeadAttachment.lead_id == lead.id,
        LeadAttachment.external_source.in_(["smartmoving", "smartmoving_document_s3"]),
    ).all()
    existing_by_id = {
        (row.job_id or "", (row.source_external_id or "").strip()): row
        for row in existing_rows
        if (row.source_external_id or "").strip()
    }
    existing_by_url = {
        (row.job_id or "", (row.external_url or "").strip()): row
        for row in existing_rows
        if (row.external_url or "").strip() and not (row.external_url or "").startswith("s3://")
    }

    stored = 0
    uploaded_urls: list[str] = []
    for doc in documents:
        target_job = job_by_smartmoving_id.get((doc.get("smartmoving_job_id") or "").strip())
        target_job_id = target_job.id if target_job else ""
        document_id = (doc.get("external_id") or "").strip()
        document_url = (doc.get("url") or "").strip()
        existing = (
            existing_by_id.get((target_job_id, document_id))
            if document_id
            else None
        ) or existing_by_url.get((target_job_id, document_url))
        if not existing and not target_job:
            existing = next(
                (
                    row for row in existing_rows
                    if (document_id and (row.source_external_id or "").strip() == document_id)
                    or (document_url and (row.external_url or "").strip() == document_url)
                ),
                None,
            )
        if existing and (existing.external_source or "").strip() == "smartmoving_document_s3":
            if existing.job_id:
                existing.job_id = None
                stored += 1
            continue
        fetched = download_opportunity_document(
            smartmoving_id,
            document_id=document_id,
            document_url=document_url,
        )
        content = fetched.get("content") or b""
        if not fetched.get("ok") or not content or len(content) > MAX_ATTACHMENT_SIZE_BYTES:
            logger.warning("Could not store SmartMoving document %s in S3: %s", document_id or document_url, fetched.get("error"))
            continue
        file_name = _safe_attachment_name(
            _clean_optional_text(fetched.get("file_name"))
            or doc.get("name")
            or "SmartMoving Document"
        )
        content_type = _clean_optional_text(fetched.get("content_type")) or "application/octet-stream"
        try:
            s3_url = _upload_attachment_bytes_to_s3(
                lead_id=lead.id,
                job_id=target_job.id if target_job else None,
                file_name=file_name,
                content=content,
                content_type=content_type,
                source="smartmoving-documents",
            )
        except Exception:
            logger.exception("Failed uploading SmartMoving document %s to S3", document_id or document_url)
            continue
        uploaded_urls.append(s3_url)

        row = existing or LeadAttachment(
            lead_id=lead.id,
            job_id=target_job.id if target_job else None,
            file_blob=b"",
            uploaded_by=user.id,
        )
        row.file_name = file_name
        row.content_type = content_type
        row.file_size = len(content)
        row.file_blob = b""
        row.external_url = s3_url
        row.is_external_link = True
        row.external_source = "smartmoving_document_s3"
        row.source_external_id = document_id[:255] or hashlib.sha256(document_url.encode("utf-8")).hexdigest()
        row.job_id = target_job.id if target_job else None
        if not existing:
            db.add(row)
        stored += 1

    if stored:
        try:
            db.commit()
        except Exception:
            db.rollback()
            for s3_url in uploaded_urls:
                try:
                    _delete_s3_url(s3_url)
                except Exception:
                    logger.exception("Failed cleaning orphaned SmartMoving document %s", s3_url)
            logger.exception("Failed to save SmartMoving documents for lead %s", lead.id)
            return 0

    return stored


def _serialize_lead_attachments(lead_id: str, db: Session) -> list[dict]:
    attachments = (
        db.query(LeadAttachment, User)
        .outerjoin(User, LeadAttachment.uploaded_by == User.id)
        .filter(LeadAttachment.lead_id == lead_id)
        .order_by(LeadAttachment.created_at.desc())
        .all()
    )
    items: list[dict] = []
    for attachment, uploader in attachments:
        item = attachment.to_dict()
        item["uploaded_by_name"] = uploader.name if uploader else ""
        items.append(item)
    return items


def sync_smartmoving_files(
    lead: Lead,
    user: User,
    db: Session,
    opportunity: dict | None = None,
) -> dict:
    """Sync SmartMoving documents plus opportunityFiles into CRM attachments."""
    migrated_legacy_files = _migrate_stored_attachment_blobs_to_s3(lead.id, db)
    created_document_links = _sync_smartmoving_documents_to_s3(lead, user, db)
    if opportunity is None:
        opportunity_result = get_opportunity(_clean_optional_text(lead.smartmoving_id))
        opportunity = opportunity_result.get("data") if not opportunity_result.get("error") else None
    created_s3_files = (
        _sync_opportunity_files_to_s3(lead, opportunity, user, db)
        if isinstance(opportunity, dict)
        else 0
    )
    return {
        "ok": True,
        "lead_id": lead.id,
        "created_links": created_document_links,
        "created_s3_files": created_s3_files,
        "migrated_legacy_files": migrated_legacy_files,
        "items": _serialize_lead_attachments(lead.id, db),
    }


def _sync_smartmoving_documents_for_lead(lead: Lead, user: User, db: Session) -> dict:
    _ensure_not_dispatch_write(user)
    return sync_smartmoving_files(lead, user, db)


def _download_external_attachment_or_redirect(lead: Lead, row: LeadAttachment) -> Response:
    external_url = (getattr(row, "external_url", "") or "").strip()
    is_external = bool(getattr(row, "is_external_link", False))
    if not is_external or not external_url:
        safe_name = (row.file_name or "attachment").replace('"', "")
        headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
        return Response(content=row.file_blob, media_type=row.content_type or "application/octet-stream", headers=headers)

    external_source = (getattr(row, "external_source", "") or "").strip().lower()
    if external_url.startswith("s3://") and external_source.endswith("_s3"):
        parsed = urlparse(external_url)
        configured_bucket = (os.getenv("ATTACHMENTS_BUCKET") or "").strip()
        if parsed.scheme != "s3" or not configured_bucket or parsed.netloc != configured_bucket:
            raise HTTPException(status_code=500, detail="Attachment storage is not configured")
        object_key = parsed.path.lstrip("/")
        signed_url = boto3.client("s3").generate_presigned_url(
            "get_object",
            Params={
                "Bucket": configured_bucket,
                "Key": object_key,
                "ResponseContentDisposition": f'inline; filename="{(row.file_name or "attachment").replace(chr(34), "")}"',
            },
            ExpiresIn=300,
        )
        return RedirectResponse(url=signed_url, status_code=307)

    if external_source == "smartmoving":
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


def _delete_s3_url(external_url: str) -> None:
    parsed = urlparse((external_url or "").strip())
    configured_bucket = (os.getenv("ATTACHMENTS_BUCKET") or "").strip()
    if parsed.scheme != "s3" or not configured_bucket or parsed.netloc != configured_bucket:
        return
    boto3.client("s3").delete_object(Bucket=configured_bucket, Key=parsed.path.lstrip("/"))


def _stored_attachment_bytes(row: LeadAttachment) -> bytes | None:
    external_url = (row.external_url or "").strip()
    external_source = (row.external_source or "").strip().lower()
    if external_url.startswith("s3://") and external_source.endswith("_s3"):
        parsed = urlparse(external_url)
        configured_bucket = (os.getenv("ATTACHMENTS_BUCKET") or "").strip()
        if parsed.netloc != configured_bucket:
            return None
        return boto3.client("s3").get_object(Bucket=configured_bucket, Key=parsed.path.lstrip("/"))["Body"].read()
    if not row.is_external_link:
        return bytes(row.file_blob or b"")
    return None


@router.post("/leads/{lead_id}/attachments/download")
def download_lead_attachments(
    lead_id: str,
    body: AttachmentDownloadBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    requested = {str(value).strip() for value in (body.attachment_ids or []) if str(value).strip()}
    query = db.query(LeadAttachment).filter(LeadAttachment.lead_id == lead.id)
    if requested:
        query = query.filter(LeadAttachment.id.in_(requested))
    rows = query.order_by(LeadAttachment.created_at.asc()).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No files found")

    archive = io.BytesIO()
    used_names: set[str] = set()
    skipped: list[str] = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for row in rows:
            content = _stored_attachment_bytes(row)
            if content is None:
                skipped.append(row.file_name or row.id)
                continue
            name = _safe_attachment_name(row.file_name or row.id)
            stem, extension = os.path.splitext(name)
            candidate = name
            suffix = 2
            while candidate.lower() in used_names:
                candidate = f"{stem}-{suffix}{extension}"
                suffix += 1
            used_names.add(candidate.lower())
            bundle.writestr(candidate, content)
        if skipped:
            bundle.writestr("files-not-included.txt", "The following link-only files could not be included:\n" + "\n".join(skipped))
    archive.seek(0)
    safe_lead_name = _safe_attachment_name(lead.full_name or "lead")
    bucket = (os.getenv("ATTACHMENTS_BUCKET") or "").strip()
    if not bucket:
        raise HTTPException(status_code=500, detail="Attachment storage is not configured")
    download_name = f"{safe_lead_name}-files.zip"
    object_key = f"downloads/{lead.id}/{uuid4()}/{download_name}"
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=archive.getvalue(),
        ContentType="application/zip",
        ContentDisposition=f'attachment; filename="{download_name}"',
        ServerSideEncryption="AES256",
    )
    signed_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key, "ResponseContentDisposition": f'attachment; filename="{download_name}"'},
        ExpiresIn=300,
    )
    return RedirectResponse(url=signed_url, status_code=307)


@router.get("/leads/{lead_id}/jobs/{job_id}/attachments")
def list_job_attachments(
    lead_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)
    job = _get_job_or_404(lead_id, job_id, user, db)
    _migrate_stored_attachment_blobs_to_s3(lead_id, db)
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
    _ensure_attachment_job_column(db)
    _ensure_attachment_link_columns(db)
    job = _get_job_or_404(lead_id, job_id, user, db)

    file_name = (file.filename or "").strip()
    if not file_name:
        raise HTTPException(status_code=400, detail="File name is required")

    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(payload) > MAX_ATTACHMENT_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 15 MB)")

    content_type = file.content_type or "application/octet-stream"
    external_url = _upload_attachment_bytes_to_s3(
        lead_id=lead_id,
        job_id=job.id,
        file_name=file_name,
        content=payload,
        content_type=content_type,
        source="crm",
    )
    row = LeadAttachment(
        lead_id=lead_id,
        job_id=job.id,
        file_name=_safe_attachment_name(file_name),
        content_type=content_type,
        file_size=len(payload),
        file_blob=b"",
        external_url=external_url,
        is_external_link=True,
        external_source="crm_s3",
        uploaded_by=user.id,
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        _delete_s3_url(external_url)
        raise
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
    job = _get_job_or_404(lead_id, job_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.job_id == job.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    external_url = row.external_url or ""
    should_delete_s3 = (row.external_source or "").strip().lower().endswith("_s3")
    db.delete(row)
    db.commit()
    if should_delete_s3:
        try:
            _delete_s3_url(external_url)
        except Exception:
            logger.exception("Failed cleaning S3 file after deleting attachment %s", attachment_id)
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
    _migrate_stored_attachment_blobs_to_s3(lead.id, db)
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


@router.patch("/leads/{lead_id}/attachments/{attachment_id}/job")
def move_attachment_to_job(
    lead_id: str,
    attachment_id: str,
    body: AttachmentMoveBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin users can move files between jobs")
    lead = _get_visible_lead_or_404(lead_id, user, db)
    target_job_id = (body.job_id or "").strip()
    if target_job_id:
        target_job = (
            db.query(LeadJob)
            .filter(LeadJob.id == target_job_id, LeadJob.lead_id == lead.id)
            .first()
        )
        if not target_job:
            raise HTTPException(status_code=404, detail="Target job not found")
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    row.job_id = target_job_id or None
    db.commit()
    db.refresh(row)
    return row.to_dict()


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

    content_type = file.content_type or "application/octet-stream"
    external_url = _upload_attachment_bytes_to_s3(
        lead_id=lead.id,
        job_id=None,
        file_name=file_name,
        content=payload,
        content_type=content_type,
        source="crm",
    )
    row = LeadAttachment(
        lead_id=lead.id,
        file_name=_safe_attachment_name(file_name),
        content_type=content_type,
        file_size=len(payload),
        file_blob=b"",
        external_url=external_url,
        is_external_link=True,
        external_source="crm_s3",
        uploaded_by=user.id,
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        _delete_s3_url(external_url)
        raise
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
    if user.role not in ("admin", "sales_rep"):
        raise HTTPException(status_code=403, detail="This role cannot delete files")
    _ensure_attachment_link_columns(db)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    row = (
        db.query(LeadAttachment)
        .filter(LeadAttachment.id == attachment_id, LeadAttachment.lead_id == lead.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    external_url = row.external_url or ""
    should_delete_s3 = (row.external_source or "").strip().lower().endswith("_s3")
    db.delete(row)
    db.commit()
    if should_delete_s3:
        try:
            _delete_s3_url(external_url)
        except Exception:
            logger.exception("Failed cleaning S3 file after deleting attachment %s", attachment_id)
    return {"ok": True}


@router.patch("/leads/{lead_id}/attachments/{attachment_id}")
def rename_lead_attachment(
    lead_id: str,
    attachment_id: str,
    body: AttachmentRenameBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "sales_rep"):
        raise HTTPException(status_code=403, detail="This role cannot rename files")
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
    foreman_id: str | None = None
    notes: str | None = None
    customer_notes: str | None = None
    foreman_notes: str | None = None
    pickup_zip: str | None = None
    delivery_zip: str | None = None
    stops: list[str] | None = None
    pickup_addresses: list[str] | None = Field(default=None, alias="pickupAddresses")
    delivery_addresses: list[str] | None = Field(default=None, alias="deliveryAddresses")
    move_date: str | None = None
    booked_move_date: str | None = None
    price: float | None = None
    estimated_charges: list[LeadJobChargePayload] | None = Field(default=None, alias="estimatedCharges")
    logs: list[ExternalLeadUpdateLog] | None = None


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
    logs: list[ExternalLeadUpdateLog] | None = None


@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: str,
    body: LeadUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _apply_lead_update(lead_id, body, user, db)


def _sync_smartmoving_job_details(lead: Lead, db: Session) -> None:
    """Best-effort sync of per-job notes and estimated materials."""
    opportunity_id = _clean_optional_text(lead.smartmoving_id)
    if not opportunity_id or (lead.status or "").strip().lower() not in SMARTMOVING_JOB_DETAIL_STATUSES:
        return

    jobs = db.query(LeadJob).filter(LeadJob.lead_id == lead.id).all()
    changed = False
    for job in jobs:
        job_id = _clean_optional_text(job.smartmoving_job_id)
        if not job_id:
            continue
        result = get_opportunity_job(opportunity_id, job_id)
        detail = result.get("data")
        if result.get("error") or not isinstance(detail, dict):
            logger.warning(
                "Non-fatal SmartMoving job detail sync failure: lead_id=%s job_id=%s error=%s",
                lead.id,
                job_id,
                result.get("error") or "invalid response",
            )
            continue

        notes = detail.get("notes") if isinstance(detail.get("notes"), dict) else {}
        job.notes = str(notes.get("internalNotes") or "").strip() or None
        job.customer_notes = str(notes.get("customerNotes") or "").strip() or None
        job.foreman_notes = str(notes.get("crewNotes") or "").strip() or None
        materials = detail.get("estimatedMaterials")
        job.estimated_materials = json.dumps(materials if isinstance(materials, list) else [])
        changed = True

    if changed:
        db.commit()


def _apply_lead_update(
    lead_id: str,
    body: LeadUpdate,
    user: User,
    db: Session,
    *,
    allow_dispatch_smartmoving_refresh: bool = False,
):
    if not (allow_dispatch_smartmoving_refresh and user.role == "dispatch"):
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
        if booked_raw:
            parsed_booked = _parse_booked_move_date(booked_raw)
            if not parsed_booked:
                raise HTTPException(status_code=400, detail="booked_move_date must be a valid date")
            lead.booked_move_date = parsed_booked
    if body.move_type is not None:
        lead.move_type = body.move_type.strip()
    if body.referral_source is not None:
        lead.referral_source = body.referral_source.strip() or None
    if body.estimated_total is not None:
        current_total = _deserialize_estimated_total(lead.estimated_total) or {}
        merged_total = _merge_partial_models([body.estimated_total], [current_total])[0]
        lead.estimated_total = _serialize_estimated_total(merged_total)
    if body.payments is not None:
        existing_payments = _deserialize_payments(lead.payments)
        if user.role not in ("admin", "sales_rep"):
            for index, payment in enumerate(body.payments):
                existing = existing_payments[index] if index < len(existing_payments) else {}
                submitted = (bool(payment.rep_paid), (payment.rep_paid_at or "").strip())
                current = (
                    bool(existing.get("repPaid") or False),
                    str(existing.get("repPaidAt") or "").strip(),
                )
                if (
                    {"rep_paid", "rep_paid_at"}.intersection(payment.model_fields_set)
                    and submitted != current
                ):
                    raise HTTPException(status_code=403, detail="Only admin and sales reps can mark rep payments")
        if user.role != "admin":
            rep_commission_fields = {"rep_commission_percent", "rep_commission_amount"}
            for index, payment in enumerate(body.payments):
                existing = existing_payments[index] if index < len(existing_payments) else {}
                submitted_commission = (payment.rep_commission_percent, payment.rep_commission_amount)
                existing_commission = (existing.get("repCommissionPercent"), existing.get("repCommissionAmount"))
                if rep_commission_fields.intersection(payment.model_fields_set) and submitted_commission != existing_commission:
                    raise HTTPException(status_code=403, detail="Only admins can manage lead rep commission overrides")
            third_party_fields = {
                "third_party_commission_to",
                "third_party_commission_amount",
                "third_party_commission_paid",
                "third_party_commission_paid_at",
            }
            for index, payment in enumerate(body.payments):
                existing = existing_payments[index] if index < len(existing_payments) else {}
                submitted_third_party = (
                    (payment.third_party_commission_to or "").strip(),
                    float(payment.third_party_commission_amount or 0),
                    bool(payment.third_party_commission_paid),
                    (payment.third_party_commission_paid_at or "").strip(),
                )
                existing_third_party = (
                    str(existing.get("thirdPartyCommissionTo") or "").strip(),
                    float(existing.get("thirdPartyCommissionAmount") or 0),
                    bool(existing.get("thirdPartyCommissionPaid") or False),
                    str(existing.get("thirdPartyCommissionPaidAt") or "").strip(),
                )
                if (
                    third_party_fields.intersection(payment.model_fields_set)
                    and submitted_third_party != existing_third_party
                ):
                    raise HTTPException(status_code=403, detail="Only admins can manage third-party payouts")
        merged_payments = _merge_partial_models(body.payments, existing_payments)
        for payment in merged_payments:
            if payment.third_party_commission_amount < 0:
                raise HTTPException(status_code=400, detail="thirdPartyCommissionAmount must be >= 0")
            if payment.third_party_commission_amount > payment.amount:
                raise HTTPException(
                    status_code=400,
                    detail="thirdPartyCommissionAmount cannot exceed the payment amount",
                )
            if payment.rep_commission_percent is not None and not 0 <= payment.rep_commission_percent <= 100:
                raise HTTPException(status_code=400, detail="repCommissionPercent must be between 0 and 100")
            commissionable_amount = max(0, payment.amount - payment.third_party_commission_amount)
            if payment.rep_commission_amount is not None and not 0 <= payment.rep_commission_amount <= commissionable_amount:
                raise HTTPException(status_code=400, detail="repCommissionAmount cannot exceed the commissionable payment amount")
        lead.payments = _serialize_payments(merged_payments)

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

            if "foreman_id" in job_payload:
                if user.role not in ("admin", "dispatch"):
                    raise HTTPException(status_code=403, detail="Only admin or dispatch can assign a foreman")
                next_foreman_id = (job_payload.get("foreman_id") or "").strip()
                if not next_foreman_id:
                    target_job.foreman_id = None
                else:
                    foreman = db.query(User).filter(User.id == next_foreman_id, User.role == "foreman").first()
                    if not foreman:
                        raise HTTPException(status_code=404, detail="Foreman not found")
                    if user.role == "dispatch" and foreman.manager_dispatch_id != user.id:
                        raise HTTPException(status_code=403, detail="You can only assign your own foremen")
                    foreman_company = db.query(UserCompany).filter(
                        UserCompany.user_id == foreman.id,
                        UserCompany.company_id == target_job.company_id,
                    ).first()
                    if not foreman_company:
                        raise HTTPException(status_code=400, detail="Foreman is not assigned to this job's company")
                    target_job.foreman_id = foreman.id

            if "notes" in job_payload:
                target_job.notes = (job_payload.get("notes") or "").strip() or None
            if "customer_notes" in job_payload:
                target_job.customer_notes = (job_payload.get("customer_notes") or "").strip() or None
            if "foreman_notes" in job_payload:
                target_job.foreman_notes = (job_payload.get("foreman_notes") or "").strip() or None

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
                _validate_job_route_has_one_side(next_pickup, next_delivery)
                target_job.pickup_zip = next_pickup
                target_job.delivery_zip = next_delivery
                _persist_job_route(db, target_job.id, next_pickup, next_stops, next_delivery)

            if "move_date" in job_payload:
                target_job.move_date = _normalize_move_date(job_payload.get("move_date") or "")

            if "booked_move_date" in job_payload:
                booked_raw = (job_payload.get("booked_move_date") or "").strip()
                if booked_raw:
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
    _sync_smartmoving_job_details(lead, db)

    # If assignment changed to a new rep, send the rep_assignment SMS.
    will_send_rep_assignment_sms = (
        body.assigned_to is not None
        and bool(lead.assigned_to)
        and lead.assigned_to != prev_assigned_to
    )
    logger.info(
        "Rep-assignment call check: lead_id=%s body_assigned_to=%r previous_assigned_to=%r current_assigned_to=%r will_call=%s",
        lead.id,
        body.assigned_to,
        prev_assigned_to,
        lead.assigned_to,
        will_send_rep_assignment_sms,
    )
    if (
        will_send_rep_assignment_sms
    ):
        try:
            _send_rep_assignment_sms(lead, db)
        except Exception as exc:
            logger.warning("Non-fatal rep_assignment SMS failure for lead %s: %s", lead.id, exc)

    return lead.to_dict()


@router.post("/leads/{lead_id}/refresh-smartmoving")
def refresh_lead_from_smartmoving(
    lead_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    capture_token, outbound_logs = begin_request_capture()
    try:
        return _refresh_lead_from_smartmoving(lead_id, request, user, db, outbound_logs)
    finally:
        finish_request_capture(capture_token)


def _refresh_lead_from_smartmoving(
    lead_id: str,
    request: Request,
    user: User,
    db: Session,
    outbound_logs: list[dict[str, Any]],
):
    if user.role not in ("admin", "sales_rep", "dispatch"):
        raise HTTPException(status_code=403, detail="This role cannot refresh SmartMoving data")
    lead = _get_visible_lead_or_404(lead_id, user, db)
    smartmoving_id = _clean_optional_text(lead.smartmoving_id)
    if not smartmoving_id:
        raise HTTPException(status_code=400, detail="Lead does not have a smartmoving_id")

    opportunity_result = get_opportunity(smartmoving_id)
    if opportunity_result.get("error"):
        record_lead_update_log(
            lead_id=lead.id,
            actor_user_id=user.id,
            actor_name=user.name,
            source="smartmoving",
            method="POST",
            endpoint=f"/api/leads/{lead.id}/refresh-smartmoving",
            event_type="smartmoving_refresh",
            request_payload={"smartmoving_id": smartmoving_id, "logs": outbound_logs},
            external_response={"opportunity": opportunity_result},
            response_status=502,
            error=str(opportunity_result.get("error") or ""),
        )
        error_text = str(opportunity_result.get("error") or "")
        lowered = error_text.lower()
        if "http 400" in lowered and "opportunity was not found" in lowered:
            if user.role == "dispatch":
                raise HTTPException(
                    status_code=502,
                    detail="SmartMoving opportunity was not found; the CRM lead was not changed",
                )
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
        record_lead_update_log(
            lead_id=lead.id,
            actor_user_id=user.id,
            actor_name=user.name,
            source="smartmoving",
            method="POST",
            endpoint=f"/api/leads/{lead.id}/refresh-smartmoving",
            event_type="smartmoving_refresh",
            request_payload={"smartmoving_id": smartmoving_id, "logs": outbound_logs},
            external_response={"opportunity": opportunity_result},
            response_status=502,
            error="SmartMoving refresh returned an invalid payload",
        )
        raise HTTPException(status_code=502, detail="SmartMoving refresh returned an invalid payload")

    payload = _build_smartmoving_refresh_payload(opportunity, user)

    if isinstance(payload.get("payments"), list):
        existing_payments = _deserialize_payments(lead.payments)
        payload["payments"] = _merge_smartmoving_payments_with_existing(payload.get("payments") or [], existing_payments)

    audit_result = get_opportunity_audit_activity(smartmoving_id)
    if audit_result.get("error"):
        record_lead_update_log(
            lead_id=lead.id,
            actor_user_id=user.id,
            actor_name=user.name,
            source="smartmoving",
            method="POST",
            endpoint=f"/api/leads/{lead.id}/refresh-smartmoving",
            event_type="smartmoving_refresh",
            request_payload={"smartmoving_id": smartmoving_id, "mapped_payload": payload, "logs": outbound_logs},
            external_response={"opportunity": opportunity_result, "audit_activity": audit_result},
            response_status=502,
            error=str(audit_result.get("error") or ""),
        )
        raise HTTPException(status_code=502, detail=f"SmartMoving audit failed: {audit_result['error']}")
    audit_rows = audit_result.get("data")
    if not isinstance(audit_rows, list):
        record_lead_update_log(
            lead_id=lead.id,
            actor_user_id=user.id,
            actor_name=user.name,
            source="smartmoving",
            method="POST",
            endpoint=f"/api/leads/{lead.id}/refresh-smartmoving",
            event_type="smartmoving_refresh",
            request_payload={"smartmoving_id": smartmoving_id, "mapped_payload": payload, "logs": outbound_logs},
            external_response={"opportunity": opportunity_result, "audit_activity": audit_result},
            response_status=502,
            error="SmartMoving audit returned an invalid payload",
        )
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
    smartmoving_created_time = _clean_optional_text(payload.get("created_time"))
    if smartmoving_created_time:
        # This value belongs to SmartMoving and must not fall back to the CRM
        # record creation timestamp. Persist it only when SmartMoving
        # actually returned createdAtUtc.
        lead.created_time = smartmoving_created_time
    updated = _apply_lead_update(
        lead.id,
        body,
        user,
        db,
        allow_dispatch_smartmoving_refresh=True,
    )
    sync_result = sync_smartmoving_files(lead, user, db, opportunity)
    request.state.audit_request_payload = {
        "smartmoving_id": smartmoving_id,
        "mapped_payload": payload,
        "logs": outbound_logs,
    }
    if isinstance(updated, dict):
        updated["smartmoving_document_links_synced"] = sync_result["created_links"]
        updated["smartmoving_opportunity_files_saved"] = sync_result["created_s3_files"]
    return updated


@router.post("/leads/{lead_id}/sync-smartmoving-documents")
def sync_smartmoving_documents(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync SmartMoving document links into CRM attachment rows without running a full lead refresh."""
    lead = _get_visible_lead_or_404(lead_id, user, db)
    return _sync_smartmoving_documents_for_lead(lead, user, db)


@router.post("/leads/by-smartmoving/{smartmoving_id}/sync-smartmoving-documents")
def sync_smartmoving_documents_by_smartmoving_id(
    smartmoving_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync SmartMoving document links by SmartMoving opportunity id."""
    lead = _get_visible_lead_by_smartmoving_or_404(smartmoving_id, user, db)
    return _sync_smartmoving_documents_for_lead(lead, user, db)


def _send_rep_assignment_sms(lead: Lead, db: Session) -> None:
    logger.info(
        "ENTER _send_rep_assignment_sms: lead_id=%s assigned_to=%s REP_ASSIGNMENT_SMS_DRY_RUN=%r",
        lead.id,
        lead.assigned_to,
        os.getenv("REP_ASSIGNMENT_SMS_DRY_RUN"),
    )
    if (lead.status or "").strip().lower() in NO_MESSAGE_STATUSES:
        return
    if not lead.phone:
        return
    rep = db.query(User).filter(User.id == lead.assigned_to).first()
    company = db.query(Company).filter(Company.id == lead.company_id).first()
    if not rep or not company:
        return

    template = get_company_template(db, company.id, "rep_assignment_sms")
    first_name = lead.full_name.split()[0] if (lead.full_name or "").strip() else ""
    message = render_template(
        template,
        first_name=first_name,
        company_name=company.name,
        company_phone=company.phone or "",
        smartmoving_id=lead.smartmoving_id or "",
        rep_name=rep.name or "",
    )

    dry_run = os.getenv("REP_ASSIGNMENT_SMS_DRY_RUN", "true").strip().lower() == "true"
    if dry_run:
        sms_result = {
            "ok": False,
            "dry_run": True,
            "would_send_to": lead.phone,
            "message": message,
        }
        logger.info("Rep-assignment SMS dry run for lead %s: %s", lead.id, sms_result)
    else:
        from libs.aircall import send_sms, find_number_id

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
            qualified=bool(sms_result.get("ok")) or dry_run,
            qualification_reason="dry_run" if dry_run else ("ok" if sms_result.get("ok") else (sms_result.get("error") or "sms_failed")),
            message=message,
            messenger=False,
            aircall=True,
            dry_run=dry_run,
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
    logs: list[ExternalLeadUpdateLog] | None = None
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

    # A Referral Source rule routes immediately and independently of date rules.
    # Without a matching rule, retain the existing admin-availability behavior.
    configured_rep_ids = configured_rep_ids_for_referral(db, company.id, body.referral_source)
    should_auto_assign = configured_rep_ids is not None or not _any_admin_available_now(db)
    if not assigned_to_user_id and should_auto_assign:
        available_rep_ids = configured_rep_ids if configured_rep_ids is not None else _active_available_rep_ids(db)
        conflicts = find_assignment_conflicts(
            db,
            company_id=company.id,
            phone=body.phone_number,
            email=body.email,
        )
        if conflicts.same_company_match:
            assignment_mode = "queued"
            assignment_reason = "matching_assigned_lead_same_company"
        elif configured_rep_ids is not None:
            # A Referral Source rule chooses from its complete configured pool.
            # Do not silently route to a different rule rep when the selected rep
            # already owns this client under another company.
            rep = _pick_round_robin_rep_for_company(
                company.id,
                db,
                available_rep_ids,
                respect_availability=False,
            )
            if rep and rep.id in conflicts.excluded_rep_ids:
                assignment_mode = "queued"
                assignment_reason = "referral_source_rule_rep_has_matching_lead_other_company"
            elif rep:
                assigned_to_user_id = rep.id
                assignment_mode = "auto"
                assignment_reason = "referral_source_rule_round_robin"
            else:
                assignment_mode = "queued"
                assignment_reason = "referral_source_rule_no_available_rep"
        else:
            eligible_rep_ids = available_rep_ids - conflicts.excluded_rep_ids
            rep = _pick_round_robin_rep_for_company(
                company.id,
                db,
                eligible_rep_ids,
                respect_availability=True,
            )
            if rep:
                assigned_to_user_id = rep.id
                assignment_mode = "auto"
                assignment_reason = (
                    "matching_lead_other_company_excluded_previous_rep"
                    if conflicts.excluded_rep_ids
                    else "all_admins_unavailable_round_robin"
                )
            else:
                assignment_mode = "queued"
                assignment_reason = (
                    "matching_lead_other_company_excluded_all_reps"
                    if conflicts.excluded_rep_ids
                    else "all_admins_unavailable_no_available_rep"
                )

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

    auto_assignment_dry_run = os.getenv("AUTO_ASSIGN_DRY_RUN_ONLY", "false").strip().lower() == "true"
    persisted_assignee_id = None if assignment_mode == "auto" and auto_assignment_dry_run else assigned_to_user_id

    lead = Lead(
        company_id=company.id,
        assigned_to=persisted_assignee_id,
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
        if auto_assignment_dry_run:
            logger.info(
                "DEV dry run: would auto-assign lead %s to rep %s; CRM and SmartMoving unchanged",
                lead.id,
                assigned_rep.id if assigned_rep else None,
            )
        elif not assigned_rep:
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
                send_assignment_webhook(lead, assigned_rep)

    # Send welcome SMS if phone and smartmoving_id are present
    sms_result = None
    message = ""
    new_lead_sms_dry_run = os.getenv("NEW_LEAD_SMS_DRY_RUN", "true").strip().lower() == "true"
    if not suppress_new_lead_automation and lead.phone and lead.smartmoving_id:
        first_name = lead.full_name.split()[0] if lead.full_name.strip() else ""
        template = get_company_template(db, company.id, "welcome_sms")
        message = render_template(
        template,
            first_name=first_name,
            company_name=company.name,
            smartmoving_id=lead.smartmoving_id,
            company_phone=company.phone or "",
            rep_name="",
        )

        if new_lead_sms_dry_run:
            sms_result = {
                "ok": False,
                "dry_run": True,
                "would_send_to": lead.phone,
                "message": message,
            }
            logger.info("Welcome SMS dry run for lead %s: %s", lead.id, sms_result)
        else:
            from libs.aircall import send_sms, find_number_id

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
    if assignment_reason == "matching_assigned_lead_same_company":
        assign_note = "Not auto-assigned because the same phone or email is already assigned in this company"
    elif assignment_reason == "referral_source_rule_rep_has_matching_lead_other_company":
        assign_note = "Not auto-assigned because the rule-selected rep already has the same phone or email under another company"
    elif assignment_reason == "matching_lead_other_company_excluded_all_reps":
        assign_note = "Not auto-assigned because matching leads in other companies are assigned to every eligible rep"
    elif assignment_mode == "auto" and auto_assignment_dry_run:
        excluded_note = (
            "; excluded reps already assigned to matching leads in other companies"
            if assignment_reason == "matching_lead_other_company_excluded_previous_rep"
            else ""
        )
        assign_note = f"DRY RUN: would auto assign new lead to {assigned_rep.name if assigned_rep else 'unknown rep'}{excluded_note}"
    else:
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
            assigned_to=assigned_rep.id if assignment_mode == "auto" and auto_assignment_dry_run and assigned_rep else lead.assigned_to,
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
                dry_run=new_lead_sms_dry_run,
            )
            db.add(outreach_event)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Non-fatal outreach event write failure for lead %s: %s", lead.id, exc)

    if not status_provided and not suppress_new_lead_automation and lead.referral_source:
        duplication_rules = (
            db.query(LeadDuplicationRule)
            .options(joinedload(LeadDuplicationRule.target_company))
            .filter(
                LeadDuplicationRule.source_company_id == company.id,
                LeadDuplicationRule.source_referral_source == lead.referral_source,
                LeadDuplicationRule.active.is_(True),
            )
            .all()
        )
        for duplication_rule in duplication_rules:
            _enqueue_lead_for_duplication(
                lead_id=lead.id,
                target_company_name=duplication_rule.target_company.name,
                target_referral_source=duplication_rule.target_referral_source,
                delay_minutes=duplication_rule.delay_minutes,
            )

    publish_realtime_event({
        "type": "lead_activity_changed",
        "event_id": f"lead-created:{lead.id}",
        "action": "created",
        "lead_id": lead.id,
    })

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
