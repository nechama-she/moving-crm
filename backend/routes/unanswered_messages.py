"""Admin-only API for the new Unanswered Messages page."""

import base64
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from auth import require_admin
from database import get_db
from db import calls_table, conversations_table, sms_messages_table
from models import AppSetting, Company, Lead, MessageState, MissedCallState, User
from realtime import publish_realtime_event

router = APIRouter(prefix="/api/unanswered-messages", tags=["Unanswered Messages"])
logger = logging.getLogger("moving-crm")
IGNORED_CALL_NUMBERS_SETTING = "sales_work_queue.ignored_call_numbers"
COMMUNICATION_TIMESTAMP_INDEX = "record-type-timestamp-index"
_first_contact_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "contacts": {}}
_followup_calls_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "calls": []}
_followup_messages_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "messages": []}
_followup_rows_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "rows": []}

CALL_PERIODS = (
    ("morning", 8, 12),
    ("afternoon", 12, 17),
    ("evening", 17, 20),
)
OPEN_SALES_STATUSES = ("new", "contacted", "quoted")
MIRIT_COMPANY_NAME = "mirit great american"


def _open_sales_status_filter():
    normalized_status = func.lower(func.trim(func.coalesce(Lead.status, "")))
    return normalized_status.in_((*OPEN_SALES_STATUSES, ""))


def _exclude_mirit_company_filter():
    return ~Lead.company.has(func.lower(func.trim(Company.name)) == MIRIT_COMPANY_NAME)


class EndStateRequest(BaseModel):
    channel: str
    message_id: str
    ended: bool


class IgnoreMissedCallRequest(BaseModel):
    client_identifier: str
    company_identifier: str


class IgnoredNumberRequest(BaseModel):
    number: str


def _digits(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _epoch(value: object) -> float:
    try:
        number = float(value or 0)
        return number / 1000 if number >= 1_000_000_000_000 else number
    except (TypeError, ValueError):
        return 0


def _smartmoving_created_at(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(_epoch(text), tz=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _query_since(table, record_type: str, since: int) -> list[dict]:
    items: list[dict] = []
    response = table.query(
        IndexName=COMMUNICATION_TIMESTAMP_INDEX,
        KeyConditionExpression=Key("record_type").eq(record_type) & Key("timestamp").gte(since),
        ScanIndexForward=True,
    )
    while True:
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            return items
        response = table.query(
            IndexName=COMMUNICATION_TIMESTAMP_INDEX,
            KeyConditionExpression=Key("record_type").eq(record_type) & Key("timestamp").gte(since),
            ScanIndexForward=True,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )


def _first_contact_tracking() -> tuple[datetime | None, dict[tuple[str, str, str], datetime]]:
    now = time.time()
    if _first_contact_cache["tracking_start"] is not None and now - _first_contact_cache["loaded_at"] < 30:
        return _first_contact_cache["tracking_start"], _first_contact_cache["contacts"]
    first_page = calls_table.query(
        IndexName=COMMUNICATION_TIMESTAMP_INDEX,
        KeyConditionExpression=Key("record_type").eq("call"),
        ScanIndexForward=True,
        Limit=1,
    )
    first_items = first_page.get("Items", [])
    if not first_items:
        return None, {}
    first_epoch = _epoch(first_items[0].get("timestamp"))
    tracking_start = datetime.fromtimestamp(first_epoch, tz=timezone.utc)
    calls = _query_since(calls_table, "call", int(first_epoch))
    contacts: dict[tuple[str, str, str], datetime] = {}

    def record_contact(key: tuple[str, str, str], raw_timestamp: object) -> None:
        if not key[1] or not key[2]:
            return
        occurred_at = datetime.fromtimestamp(_epoch(raw_timestamp), tz=timezone.utc)
        previous = contacts.get(key)
        if previous is None or occurred_at > previous:
            contacts[key] = occurred_at

    for item in calls:
        if str(item.get("direction") or "").strip().lower() == "outbound":
            record_contact(
                ("phone", _digits(item.get("phone_number")), _digits(item.get("company_number"))),
                item.get("timestamp"),
            )
    _first_contact_cache.update({"loaded_at": now, "tracking_start": tracking_start, "contacts": contacts})
    return tracking_start, contacts


def _followup_call_tracking() -> tuple[datetime | None, list[dict]]:
    now = time.time()
    if _followup_calls_cache["tracking_start"] is not None and now - _followup_calls_cache["loaded_at"] < 30:
        return _followup_calls_cache["tracking_start"], _followup_calls_cache["calls"]
    first_page = calls_table.query(
        IndexName=COMMUNICATION_TIMESTAMP_INDEX,
        KeyConditionExpression=Key("record_type").eq("call"),
        ScanIndexForward=True,
        Limit=1,
    )
    first_items = first_page.get("Items", [])
    if not first_items:
        return None, []
    first_epoch = _epoch(first_items[0].get("timestamp"))
    calls = _query_since(calls_table, "call", int(first_epoch))
    outbound = [item for item in calls if str(item.get("direction") or "").strip().lower() == "outbound"]
    tracking_start = datetime.fromtimestamp(first_epoch, tz=timezone.utc)
    _followup_calls_cache.update({"loaded_at": now, "tracking_start": tracking_start, "calls": outbound})
    return tracking_start, outbound


def _followup_message_tracking(tracking_start: datetime) -> list[dict]:
    now = time.time()
    cached_start = _followup_messages_cache["tracking_start"]
    if cached_start == tracking_start and now - _followup_messages_cache["loaded_at"] < 30:
        return _followup_messages_cache["messages"]
    since_epoch = int(tracking_start.timestamp())
    with ThreadPoolExecutor(max_workers=2) as executor:
        sms_future = executor.submit(_query_since, sms_messages_table, "message", since_epoch)
        meta_future = executor.submit(_query_since, conversations_table, "message", since_epoch * 1000)
        sms_messages, meta_messages = sms_future.result(), meta_future.result()
    messages: list[dict] = []
    for item in sms_messages:
        direction = str(item.get("direction") or "").strip().lower()
        sender = str(item.get("sales_name") or item.get("company_name") or "").strip().lower()
        if direction not in {"sent", "outbound"} or sender in {"ai", "assistant", "bot"}:
            continue
        messages.append({
            "channel": "sms",
            "occurred_at": datetime.fromtimestamp(_epoch(item.get("timestamp")), tz=timezone.utc),
            "client": _digits(item.get("phone_number")),
            "destination": _digits(item.get("company_number")),
            "number_id": str(item.get("number_id") or "").strip(),
        })
    for item in meta_messages:
        role = str(item.get("role") or "").strip().lower()
        sender = str(item.get("sales_name") or "").strip().lower()
        if role in {"user", "client", "customer", "ai", "assistant", "bot"} or sender in {"ai", "assistant", "bot"}:
            continue
        messages.append({
            "channel": str(item.get("platform") or "messenger").strip().lower(),
            "occurred_at": datetime.fromtimestamp(_epoch(item.get("timestamp")), tz=timezone.utc),
            "client": str(item.get("user_id") or "").strip(),
            "page_id": str(item.get("page_id") or "").strip(),
        })
    messages.sort(key=lambda item: item["occurred_at"])
    _followup_messages_cache.update({"loaded_at": now, "tracking_start": tracking_start, "messages": messages})
    return messages


def _period_on(day, name: str, tz: ZoneInfo) -> tuple[datetime, datetime, str]:
    _, start_hour, end_hour = next(period for period in CALL_PERIODS if period[0] == name)
    return (
        datetime(day.year, day.month, day.day, start_hour, tzinfo=tz),
        datetime(day.year, day.month, day.day, end_hour, tzinfo=tz),
        name,
    )


def _next_period(after: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, str]:
    local = after.astimezone(tz)
    for name, start_hour, end_hour in CALL_PERIODS:
        end = datetime(local.year, local.month, local.day, end_hour, tzinfo=tz)
        if local < end:
            start = datetime(local.year, local.month, local.day, start_hour, tzinfo=tz)
            return max(start, local), end, name
    return _period_on(local.date() + timedelta(days=1), "morning", tz)


def _priority_zero_schedule(created_at: datetime, timezone_name: str) -> list[tuple[datetime, datetime, str]]:
    try:
        tz = ZoneInfo(timezone_name or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    slots: list[tuple[datetime, datetime, str]] = []
    cursor = created_at.astimezone(tz)
    for _ in range(3):
        slot = _next_period(cursor, tz)
        slots.append(slot)
        cursor = slot[1]

    third_day = slots[-1][0].date()
    third_name = slots[-1][2]
    if third_name == "morning":
        phase_two = [_period_on(third_day, "afternoon", tz), _period_on(third_day, "evening", tz)]
    elif third_name == "afternoon":
        phase_two = [_period_on(third_day, "evening", tz), _period_on(third_day + timedelta(days=1), "morning", tz)]
    else:
        phase_two = [_period_on(third_day + timedelta(days=1), "morning", tz), _period_on(third_day + timedelta(days=1), "afternoon", tz)]
    slots.extend(phase_two)
    slots.append(_period_on(phase_two[-1][0].date() + timedelta(days=1), "morning", tz))
    return slots


def _call_period_key(call_at: datetime, timezone_name: str) -> tuple[str, str] | None:
    """Identify the local call period; calls outside a required period do not count."""
    try:
        tz = ZoneInfo(timezone_name or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    local = call_at.astimezone(tz)
    for name, start_hour, end_hour in CALL_PERIODS:
        if start_hour <= local.hour < end_hour:
            return local.date().isoformat(), name
    return None


def _required_message_attempts(
    created_at: datetime,
    timezone_name: str,
    message_times: list[datetime],
    now: datetime,
) -> list[dict]:
    try:
        tz = ZoneInfo(timezone_name or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    created_local = created_at.astimezone(tz)
    local_messages = [value.astimezone(tz) for value in message_times if value >= created_at]
    definitions = (("Welcome message", 0), ("Day 2 message", 1), ("Day 3 message", 2))
    attempts = []
    for label, day_offset in definitions:
        day = created_local.date() + timedelta(days=day_offset)
        scheduled_start = created_local if day_offset == 0 else datetime(day.year, day.month, day.day, 8, tzinfo=tz)
        scheduled_end = datetime(day.year, day.month, day.day, 20, tzinfo=tz)
        completed = next((value for value in local_messages if value.date() == day), None)
        if completed:
            status = "completed"
        elif any(value > scheduled_end for value in local_messages):
            # A later outbound message makes an older missed message impossible
            # to recover. Preserve it as not sent for progress/audit purposes,
            # but do not leave it in the actionable overdue queue.
            status = "not_sent"
        elif now > scheduled_end.astimezone(timezone.utc):
            status = "overdue"
        elif now >= scheduled_start.astimezone(timezone.utc):
            status = "open"
        else:
            status = "upcoming"
        attempts.append({
            "kind": "message",
            "label": label,
            "period": "message",
            "scheduled_start": scheduled_start.isoformat(),
            "scheduled_end": scheduled_end.isoformat(),
            "completed_at": completed.isoformat() if completed else "",
            "status": status,
        })
    return attempts


def _followup_page(
    rows: list[dict],
    *,
    category: str,
    rep: str,
    company: str,
    limit: int,
    offset: int,
) -> dict:
    """Filter and paginate an already-calculated follow-up snapshot."""
    global_overdue_rows = [row for row in rows if row["overdue_count"] or row["overdue_message_count"]]
    rep_filter = rep.strip().casefold()
    company_filter = company.strip().casefold()
    filtered_rows = [
        row for row in rows
        if (not rep_filter or str(row["rep"] or "").strip().casefold() == rep_filter)
        and (not company_filter or str(row["company"] or "").strip().casefold() == company_filter)
    ]
    overdue_rows = [row for row in filtered_rows if row["overdue_count"] or row["overdue_message_count"]]
    selected = filtered_rows if category == "all" else overdue_rows
    return {
        "items": selected[offset:offset + limit],
        "counts": {"all": len(filtered_rows), "overdue": len(overdue_rows)},
        "global_counts": {"all": len(rows), "overdue": len(global_overdue_rows)},
        "filter_options": {
            "reps": sorted({str(row["rep"]) for row in rows if row["rep"]}),
            "companies": sorted({str(row["company"]) for row in rows if row["company"]}),
        },
        "has_more": offset + limit < len(selected),
    }


@router.get("/followup-calls")
def list_followup_calls(
    category: str = Query("all", pattern="^(all|overdue)$"),
    rep: str = Query(""),
    company: str = Query(""),
    refresh: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if refresh:
        _followup_calls_cache["loaded_at"] = 0.0
        _followup_messages_cache["loaded_at"] = 0.0
        _followup_rows_cache["loaded_at"] = 0.0
    tracking_start, calls = _followup_call_tracking()
    if tracking_start is None:
        return _followup_page([], category=category, rep=rep, company=company, limit=limit, offset=offset)
    now_monotonic = time.monotonic()
    if (
        _followup_rows_cache["tracking_start"] == tracking_start
        and now_monotonic - _followup_rows_cache["loaded_at"] < 30
    ):
        return _followup_page(
            _followup_rows_cache["rows"],
            category=category,
            rep=rep,
            company=company,
            limit=limit,
            offset=offset,
        )
    messages = _followup_message_tracking(tracking_start)
    candidate_leads = (
        db.query(Lead)
        .options(joinedload(Lead.company), joinedload(Lead.assignee))
        .filter(
            Lead.priority == 0,
            _open_sales_status_filter(),
            _exclude_mirit_company_filter(),
            func.length(func.trim(func.coalesce(Lead.phone, ""))) > 0,
        )
        .all()
    )
    leads_with_created_at = [
        (
            lead,
            _smartmoving_created_at(lead.created_time)
            or (lead.created_at if lead.created_at.tzinfo else lead.created_at.replace(tzinfo=timezone.utc)),
        )
        for lead in candidate_leads
    ]
    leads_with_created_at = [
        (lead, created_at)
        for lead, created_at in leads_with_created_at
        if created_at is not None and created_at >= tracking_start
    ]
    leads_with_created_at.sort(key=lambda pair: pair[1], reverse=True)
    calls_by_pair: dict[tuple[str, str], list[datetime]] = {}
    for call in calls:
        call_at = datetime.fromtimestamp(_epoch(call.get("timestamp")), tz=timezone.utc)
        key = (_digits(call.get("phone_number")), _digits(call.get("company_number")))
        calls_by_pair.setdefault(key, []).append(call_at)
    for values in calls_by_pair.values():
        values.sort()
    sms_by_phone_destination: dict[tuple[str, str], list[datetime]] = {}
    sms_by_phone_number_id: dict[tuple[str, str], list[datetime]] = {}
    meta_by_user_page: dict[tuple[str, str], list[datetime]] = {}
    for message in messages:
        occurred_at = message["occurred_at"]
        if message["channel"] == "sms":
            if message.get("destination"):
                sms_by_phone_destination.setdefault((message["client"], message["destination"]), []).append(occurred_at)
            if message.get("number_id"):
                sms_by_phone_number_id.setdefault((message["client"], message["number_id"]), []).append(occurred_at)
        elif message.get("client") and message.get("page_id"):
            meta_by_user_page.setdefault((message["client"], message["page_id"]), []).append(occurred_at)

    now = datetime.now(timezone.utc)
    rows = []
    for lead, created_at in leads_with_created_at:
        client_phone = _digits(lead.phone)
        timezone_name = lead.company.timezone if lead.company else "America/New_York"
        destinations = {_digits(lead.company.phone) if lead.company else "", _digits(lead.assignee.phone) if lead.assignee else ""}
        destinations.discard("")
        matching_calls = sorted(
            call_at
            for destination in destinations
            for call_at in calls_by_pair.get((client_phone, destination), [])
            if call_at >= created_at
        )
        # A required morning/afternoon/evening period can be completed only once.
        # Extra calls in that same local period neither complete another slot nor
        # carry forward as a delayed completion.
        seen_call_periods: set[tuple[str, str]] = set()
        lead_calls = []
        for call_at in matching_calls:
            period_key = _call_period_key(call_at, timezone_name)
            if period_key is None or period_key in seen_call_periods:
                continue
            seen_call_periods.add(period_key)
            lead_calls.append(call_at)
        slots = _priority_zero_schedule(created_at, timezone_name)
        try:
            lead_tz = ZoneInfo(timezone_name or "America/New_York")
        except Exception:
            lead_tz = ZoneInfo("America/New_York")
        call_index = 0
        attempts = []
        slot_index = 0
        while slot_index < len(slots) and len(attempts) < 6:
            start, end, period = slots[slot_index]
            start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
            while call_index < len(lead_calls) and lead_calls[call_index] < start_utc:
                call_index += 1
            completed_at = lead_calls[call_index] if call_index < len(lead_calls) else None
            if completed_at:
                call_index += 1
                status = "on_time" if completed_at <= end_utc else "delayed"
                if status == "delayed":
                    completed_local = completed_at.astimezone(lead_tz)
                    for future_index in range(slot_index + 1, len(slots)):
                        future_start, future_end, _ = slots[future_index]
                        if future_start <= completed_local < future_end:
                            del slots[future_index]
                            slots.append(_next_period(slots[-1][1], lead_tz))
                            break
            elif now > end_utc:
                status = "overdue"
            elif now >= start_utc:
                status = "open"
            else:
                status = "upcoming"
            attempts.append({
                "number": len(attempts) + 1,
                "kind": "call",
                "label": f"{period.capitalize()} call",
                "period": period,
                "scheduled_start": start.isoformat(),
                "scheduled_end": end.isoformat(),
                "completed_at": completed_at.isoformat() if completed_at else "",
                "status": status,
            })
            slot_index += 1
        message_times: set[datetime] = set()
        company_number_id = str(lead.company.aircall_number_id or "").strip() if lead.company else ""
        rep_number_id = str(lead.assignee.aircall_number_id or "").strip() if lead.assignee else ""
        for destination in destinations:
            message_times.update(sms_by_phone_destination.get((client_phone, destination), []))
        for number_id in {company_number_id, rep_number_id} - {""}:
            message_times.update(sms_by_phone_number_id.get((client_phone, number_id), []))
        facebook_user_id = str(lead.facebook_user_id or "").strip()
        facebook_page_id = str(lead.company.facebook_page_id or "").strip() if lead.company else ""
        if facebook_user_id and facebook_page_id:
            message_times.update(meta_by_user_page.get((facebook_user_id, facebook_page_id), []))
        message_attempts = _required_message_attempts(created_at, timezone_name, sorted(message_times), now)
        timeline = [*attempts, *(attempt for attempt in message_attempts if attempt["status"] != "not_sent")]
        # The UI presents each requirement by its deadline, so order the
        # checklist by that same deadline. Completion time must not move it.
        timeline.sort(key=lambda item: (item["scheduled_end"], 0 if item["kind"] == "call" else 1))
        overdue_count = sum(1 for attempt in attempts if attempt["status"] == "overdue")
        rows.append({
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "client_phone": lead.phone or "",
            "rep": lead.assignee.name if lead.assignee else "",
            "company": lead.company.name if lead.company else "",
            "created_at": created_at.isoformat(),
            "smartmoving_created_time": lead.created_time,
            "created_time_source": "smartmoving" if _smartmoving_created_at(lead.created_time) else "crm",
            "attempts": attempts,
            "message_attempts": message_attempts,
            "timeline": timeline,
            "completed_count": sum(1 for attempt in attempts if attempt["completed_at"]),
            "completed_message_count": sum(1 for attempt in message_attempts if attempt["completed_at"]),
            "overdue_message_count": sum(1 for attempt in message_attempts if attempt["status"] == "overdue"),
            "overdue_count": overdue_count,
        })
    _followup_rows_cache.update({
        "loaded_at": time.monotonic(),
        "tracking_start": tracking_start,
        "rows": rows,
    })
    return _followup_page(
        rows,
        category=category,
        rep=rep,
        company=company,
        limit=limit,
        offset=offset,
    )


@router.get("/first-contact-leads")
def list_first_contact_leads(
    category: str = Query("new", pattern="^(new|overdue)$"),
    refresh: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if refresh:
        _first_contact_cache["loaded_at"] = 0.0
    tracking_start, contacts = _first_contact_tracking()
    if tracking_start is None:
        return {"items": [], "counts": {"new": 0, "overdue": 0}, "total": 0, "has_more": False, "tracking_start": ""}
    leads = (
        db.query(Lead)
        .options(joinedload(Lead.company), joinedload(Lead.assignee))
        .filter(
            Lead.created_at >= tracking_start,
            Lead.priority == 0,
            _open_sales_status_filter(),
            _exclude_mirit_company_filter(),
        )
        .order_by(Lead.created_at.desc())
        .all()
    )
    now = datetime.now(timezone.utc)
    thirty_minutes_ago = now - timedelta(minutes=30)
    pending: dict[str, list[Lead]] = {"new": [], "overdue": []}
    for lead in leads:
        created_at = (
            _smartmoving_created_at(lead.created_time)
            or (lead.created_at if lead.created_at.tzinfo else lead.created_at.replace(tzinfo=timezone.utc))
        )
        if created_at < tracking_start:
            continue
        client_phone = _digits(lead.phone)
        company_phone = _digits(lead.company.phone) if lead.company else ""
        rep_phone = _digits(lead.assignee.phone) if lead.assignee else ""
        contact_keys = (
            ("phone", client_phone, company_phone),
            ("phone", client_phone, rep_phone),
        )
        contacted = any(contacts.get(key) is not None and contacts[key] >= created_at for key in contact_keys)
        if contacted:
            continue
        pending["new" if created_at > thirty_minutes_ago else "overdue"].append(lead)
    selected = pending[category]
    if category == "overdue":
        selected.sort(key=lambda lead: lead.created_at)
    page = selected[offset:offset + limit]
    items = []
    for lead in page:
        created_at = (
            _smartmoving_created_at(lead.created_time)
            or (lead.created_at if lead.created_at.tzinfo else lead.created_at.replace(tzinfo=timezone.utc))
        )
        items.append({
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "client_phone": lead.phone or "",
            "rep": lead.assignee.name if lead.assignee else "",
            "company": lead.company.name if lead.company else "",
            "status": lead.status or "new",
            "created_at": created_at.isoformat(),
            "age_minutes": max(0, int((now - created_at).total_seconds() // 60)),
        })
    counts = {name: len(rows) for name, rows in pending.items()}
    return {
        "items": items,
        "counts": counts,
        "total": len(selected),
        "has_more": offset + limit < len(selected),
        "tracking_start": tracking_start.isoformat(),
    }


def _ignored_call_numbers(db: Session) -> set[str]:
    row = db.query(AppSetting).filter(AppSetting.key == IGNORED_CALL_NUMBERS_SETTING).first()
    if not row or not row.value:
        return set()
    try:
        values = json.loads(row.value)
    except (TypeError, ValueError):
        logger.warning("Invalid ignored call numbers setting")
        return set()
    return {_digits(value) for value in values if _digits(value)}


def _save_ignored_call_numbers(db: Session, numbers: set[str]) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == IGNORED_CALL_NUMBERS_SETTING).first()
    value = json.dumps(sorted(numbers), separators=(",", ":"))
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=IGNORED_CALL_NUMBERS_SETTING, value=value))


def _ring_target(
    number: str,
    companies_by_phone: dict[str, str],
    reps_by_phone: dict[str, str],
) -> str:
    if number in reps_by_phone:
        return reps_by_phone[number]
    if number in companies_by_phone:
        return companies_by_phone[number]
    return "Unknown number"


@router.get("/missed-calls")
def list_missed_calls(
    limit: int = Query(100, ge=1, le=100),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    states = (
        db.query(MissedCallState)
        .options(joinedload(MissedCallState.lead).joinedload(Lead.company), joinedload(MissedCallState.lead).joinedload(Lead.assignee))
        .order_by(MissedCallState.latest_missed_at.desc())
        .all()
    )
    ignored_numbers = _ignored_call_numbers(db)
    states = [
        state for state in states
        if _digits(state.client_identifier) not in ignored_numbers
        and _digits(state.company_identifier) not in ignored_numbers
    ]
    companies_by_phone = {
        _digits(phone): name
        for name, phone in db.query(Company.name, Company.phone).all()
        if _digits(phone)
    }
    reps_by_phone = {
        _digits(phone): name
        for name, phone in db.query(User.name, User.phone).all()
        if _digits(phone)
    }
    items = []
    for state in states[:limit]:
        lead = state.lead
        ring_number = _digits(state.company_identifier)
        items.append({
            "call_id": state.call_id,
            "lead_id": state.lead_id or "",
            "client_identifier": state.client_identifier,
            "company_identifier": state.company_identifier,
            "client": lead.full_name if lead else state.client_identifier,
            "rep": lead.assignee.name if lead and lead.assignee else "Unassigned",
            "company": lead.company.name if lead and lead.company else "",
            "ring_number": ring_number,
            "ring_target": _ring_target(ring_number, companies_by_phone, reps_by_phone),
            "missed_count": state.missed_count,
            "first_missed_at": state.first_missed_at.isoformat(),
            "latest_missed_at": state.latest_missed_at.isoformat(),
        })
    return {"items": items, "count": len(states)}


@router.get("/ignored-call-numbers")
def list_ignored_call_numbers(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"numbers": sorted(_ignored_call_numbers(db))}


@router.post("/ignored-call-numbers")
def add_ignored_call_number(
    body: IgnoredNumberRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    number = _digits(body.number)
    if len(number) < 7 or len(number) > 15:
        raise HTTPException(status_code=400, detail="Phone number must contain 7 to 15 digits")
    numbers = _ignored_call_numbers(db)
    numbers.add(number)
    _save_ignored_call_numbers(db, numbers)
    call_states = db.query(MissedCallState).filter(or_(
        MissedCallState.client_identifier == number,
        MissedCallState.company_identifier == number,
    )).all()
    call_ids = [state.call_id for state in call_states]
    for state in call_states:
        db.delete(state)
    message_states = db.query(MessageState).filter(
        MessageState.channel == "sms",
        or_(MessageState.client_identifier == number, MessageState.company_identifier == number),
    ).all()
    message_ids = [state.message_id for state in message_states]
    unanswered_removed = sum(not state.conversation_ended for state in message_states)
    ended_removed = len(message_states) - unanswered_removed
    for state in message_states:
        db.delete(state)
    db.commit()
    call_event = {
        "type": "missed_call_state_changed",
        "event_id": f"ignored-number:{uuid.uuid4()}",
        "action": "remove",
        "call_ids": call_ids,
        "count_delta": -len(call_states),
    }
    message_event = {
        "type": "message_state_changed",
        "event_id": f"ignored-number:{uuid.uuid4()}",
        "action": "remove",
        "channel": "sms",
        "message_ids": message_ids,
        "count_delta": {"unanswered": -unanswered_removed, "ended": -ended_removed},
    }
    publish_realtime_event(call_event)
    publish_realtime_event(message_event)
    return {"numbers": sorted(numbers), "events": [call_event, message_event]}


@router.delete("/ignored-call-numbers/{number}")
def remove_ignored_call_number(
    number: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    normalized = _digits(number)
    numbers = _ignored_call_numbers(db)
    numbers.discard(normalized)
    _save_ignored_call_numbers(db, numbers)
    db.commit()
    return {"numbers": sorted(numbers)}


@router.delete("/missed-calls")
def ignore_missed_call(
    body: IgnoreMissedCallRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    state = db.query(MissedCallState).filter(
        MissedCallState.client_identifier == body.client_identifier.strip(),
        MissedCallState.company_identifier == body.company_identifier.strip(),
    ).first()
    if not state:
        raise HTTPException(status_code=404, detail="Missed call item not found")
    call_id = state.call_id
    db.delete(state)
    db.commit()
    realtime_event = {
        "type": "missed_call_state_changed",
        "event_id": f"manual:{uuid.uuid4()}",
        "action": "remove",
        "call_ids": [call_id],
        "count_delta": -1,
    }
    publish_realtime_event(realtime_event)
    return {"ok": True, "event": realtime_event}


def _exact_source_message(channel: str, message_id: str) -> dict:
    table = sms_messages_table if channel == "sms" else conversations_table
    response = table.query(IndexName="message_id_index", KeyConditionExpression=Key("message_id").eq(message_id), Limit=1)
    items = response.get("Items") or []
    if not items:
        return {}
    item = items[0]
    key = (
        {"phone_number": item.get("phone_number"), "timestamp": item.get("timestamp")}
        if channel == "sms"
        else {"user_id": item.get("user_id"), "timestamp": item.get("timestamp")}
    )
    if any(value is None for value in key.values()):
        return item
    return table.get_item(Key=key).get("Item") or item


def _preview_messages(states: list[MessageState]) -> dict[tuple[str, str], dict]:
    def load(state: MessageState):
        key = (state.channel, state.message_id)
        try:
            return key, _exact_source_message(*key)
        except (BotoCoreError, ClientError, TypeError, ValueError):
            logger.exception("Message preview lookup failed channel=%s message_id=%s", *key)
            return key, {}

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(states)))) as executor:
        return dict(executor.map(load, states))


@router.get("")
def list_message_states(
    ended: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    cursor: str = Query(""),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    started_at = time.perf_counter()
    ignored_numbers = _ignored_call_numbers(db)
    visible_filter = True
    if ignored_numbers:
        visible_filter = ~and_(
            MessageState.channel == "sms",
            or_(
                MessageState.client_identifier.in_(ignored_numbers),
                MessageState.company_identifier.in_(ignored_numbers),
            ),
        )
    count_rows = (
        db.query(MessageState.conversation_ended, func.count())
        .filter(visible_filter)
        .group_by(MessageState.conversation_ended)
        .all()
    )
    counts_by_ended = {bool(value): int(count) for value, count in count_rows}
    query = (
        db.query(MessageState)
        .options(joinedload(MessageState.lead).joinedload(Lead.company), joinedload(MessageState.lead).joinedload(Lead.assignee))
        .filter(visible_filter, MessageState.conversation_ended.is_(ended))
        .order_by(MessageState.occurred_at.desc(), MessageState.channel.asc(), MessageState.message_id.asc())
    )
    if cursor:
        try:
            padding = "=" * (-len(cursor) % 4)
            cursor_data = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
            cursor_time = datetime.fromisoformat(cursor_data["occurred_at"])
            cursor_channel = str(cursor_data["channel"])
            cursor_message_id = str(cursor_data["message_id"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid message cursor")
        query = query.filter(or_(
            MessageState.occurred_at < cursor_time,
            and_(MessageState.occurred_at == cursor_time, MessageState.channel > cursor_channel),
            and_(MessageState.occurred_at == cursor_time, MessageState.channel == cursor_channel, MessageState.message_id > cursor_message_id),
        ))
    page = query.limit(limit + 1).all()
    has_more = len(page) > limit
    states = page[:limit]
    sql_finished_at = time.perf_counter()
    unanswered_count = counts_by_ended.get(False, 0)
    ended_count = counts_by_ended.get(True, 0)
    messages = _preview_messages(states)
    previews_finished_at = time.perf_counter()
    companies_by_phone = {_digits(phone): name for name, phone in db.query(Company.name, Company.phone).all() if _digits(phone)}
    reps_by_phone = {_digits(phone): name for name, phone in db.query(User.name, User.phone).all() if _digits(phone)}
    items = []
    for state in states:
        lead = state.lead
        message = messages.get((state.channel, state.message_id), {})
        destination_number = _digits(state.company_identifier) if state.channel == "sms" else ""
        items.append({
            "channel": state.channel,
            "message_id": state.message_id,
            "lead_id": state.lead_id or "",
            "client_identifier": state.client_identifier,
            "company_identifier": state.company_identifier,
            "client": lead.full_name if lead else state.client_identifier,
            "client_number": _digits(state.client_identifier) if state.channel == "sms" else "",
            "message": str(message.get("text") or ""),
            "attachments": message.get("attachments") or [],
            "rep": lead.assignee.name if lead and lead.assignee else "Unassigned",
            "company": lead.company.name if lead and lead.company else "",
            "destination_number": destination_number,
            "destination_name": _ring_target(destination_number, companies_by_phone, reps_by_phone) if destination_number else "",
            "occurred_at": state.occurred_at.isoformat(),
        })
    logger.info(
        "Unanswered messages load total_rows=%d displayed_rows=%d sql_ms=%.1f previews_ms=%.1f total_ms=%.1f",
        unanswered_count + ended_count,
        len(states),
        (sql_finished_at - started_at) * 1000,
        (previews_finished_at - sql_finished_at) * 1000,
        (time.perf_counter() - started_at) * 1000,
    )
    next_cursor = ""
    if has_more and states:
        last = states[-1]
        payload = json.dumps({"occurred_at": last.occurred_at.isoformat(), "channel": last.channel, "message_id": last.message_id}, separators=(",", ":"))
        next_cursor = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "items": items,
        "counts": {"unanswered": unanswered_count, "ended": ended_count},
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.patch("/end")
def set_conversation_ended(
    body: EndStateRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    state = db.query(MessageState).filter(
        MessageState.channel == body.channel.strip().lower(),
        MessageState.message_id == body.message_id.strip(),
    ).first()
    if not state:
        raise HTTPException(status_code=404, detail="Message state not found")
    previous_ended = bool(state.conversation_ended)
    if previous_ended == body.ended:
        return {"message_id": state.message_id, "conversation_ended": previous_ended, "event": None}
    state.conversation_ended = body.ended
    db.commit()
    lead = (
        db.query(Lead)
        .options(joinedload(Lead.company), joinedload(Lead.assignee))
        .filter(Lead.id == state.lead_id)
        .first()
        if state.lead_id else None
    )
    try:
        message = _exact_source_message(state.channel, state.message_id)
    except (BotoCoreError, ClientError, TypeError, ValueError):
        logger.exception("Message preview lookup failed while changing ended state channel=%s message_id=%s", state.channel, state.message_id)
        message = {}
    company = lead.company.name if lead and lead.company else str(message.get("company_name") or "")
    if not company and state.channel != "sms":
        matched_company = db.query(Company).filter(Company.facebook_page_id == state.company_identifier).first()
        company = matched_company.name if matched_company else ""
    row = {
        "channel": state.channel,
        "message_id": state.message_id,
        "lead_id": state.lead_id or "",
        "client_identifier": state.client_identifier,
        "client": lead.full_name if lead else state.client_identifier,
        "message": str(message.get("text") or ""),
        "attachments": message.get("attachments") or [],
        "rep": lead.assignee.name if lead and lead.assignee else "Unassigned",
        "company": company,
        "occurred_at": state.occurred_at.isoformat(),
    }
    realtime_event = {
        "type": "message_state_changed",
        "event_id": f"manual:{uuid.uuid4()}",
        "action": "ended" if body.ended else "reopened",
        "row": row,
        "count_delta": {
            "unanswered": -1 if body.ended else 1,
            "ended": 1 if body.ended else -1,
        },
    }
    publish_realtime_event(realtime_event)
    return {"message_id": state.message_id, "conversation_ended": state.conversation_ended, "event": realtime_event}
