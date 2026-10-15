"""Admin-only API for the new Unanswered Messages page."""

import base64
import json
import logging
import os
import time
import uuid
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Load, Session, joinedload

from auth import require_admin
from database import get_db
from db import calls_table, conversations_table, sms_messages_table
from models import AppSetting, Company, Lead, MessageState, MissedCallState, User
from realtime import publish_realtime_event
from ended_chat_retention import visible_message_states
from work_queue_rules import _digits, _epoch, _smartmoving_created_at, calculate_followup_rows

router = APIRouter(prefix="/api/unanswered-messages", tags=["Unanswered Messages"])
logger = logging.getLogger("moving-crm")
IGNORED_CALL_NUMBERS_SETTING = "sales_work_queue.ignored_call_numbers"
COMMUNICATION_TIMESTAMP_INDEX = "record-type-timestamp-index"
_first_contact_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "contacts": {}}
_followup_calls_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "calls": []}
_followup_messages_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "messages": []}
_followup_rows_cache: dict = {"loaded_at": 0.0, "tracking_start": None, "rows": []}
_call_tracking_lock = Lock()

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


def _queue_lead_options(relationship=None):
    # Company logos and lead notes can be large. None of the queue rows need
    # them; select only the fields used by labels and contact calculations.
    lead = Load(Lead) if relationship is None else joinedload(relationship)
    return (
        lead.load_only(Lead.id, Lead.full_name, Lead.phone, Lead.status,
                       Lead.priority, Lead.created_at, Lead.created_time,
                       Lead.facebook_user_id, Lead.company_id, Lead.assigned_to),
        lead.joinedload(Lead.company).load_only(
            Company.name, Company.phone, Company.timezone,
            Company.aircall_number_id, Company.facebook_page_id),
        lead.joinedload(Lead.assignee).load_only(
            User.name, User.phone, User.aircall_number_id),
    )


class EndStateRequest(BaseModel):
    channel: str
    message_id: str
    ended: bool


class IgnoreMissedCallRequest(BaseModel):
    client_identifier: str
    company_identifier: str


class IgnoredNumberRequest(BaseModel):
    number: str
    direction: str = "both"


@router.get("/summary")
def queue_summary(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    ignored = _ignored_call_numbers(db)
    ignored_from = [number for number, directions in ignored.items() if directions & {"from", "both"}]
    ignored_to = [number for number, directions in ignored.items() if directions & {"to", "both"}]
    messages = db.query(MessageState.conversation_ended, func.count()).filter(visible_message_states(), ~and_(
        MessageState.channel == "sms", or_(MessageState.client_identifier.in_(ignored_from), MessageState.company_identifier.in_(ignored_to)),
    )).group_by(MessageState.conversation_ended).all()
    message_counts = {bool(ended): count for ended, count in messages}
    calls = db.query(MissedCallState).filter(~MissedCallState.client_identifier.in_(ignored_from), ~MissedCallState.company_identifier.in_(ignored_to)).count()
    return {"enabled": False, "ready": False,
            "messages": {"unanswered": message_counts.get(False, 0), "ended": message_counts.get(True, 0)},
            "missed_calls": calls, "first_contact": None,
            "followups": None}


def _query_since(table, record_type: str, since: int, fields: tuple[str, ...] = ()) -> list[dict]:
    items: list[dict] = []
    query = {
        "IndexName": COMMUNICATION_TIMESTAMP_INDEX,
        "KeyConditionExpression": Key("record_type").eq(record_type) & Key("timestamp").gte(since),
        "ScanIndexForward": True,
    }
    if fields:
        names = {f"#field{i}": field for i, field in enumerate(fields)}
        query.update(ProjectionExpression=", ".join(names), ExpressionAttributeNames=names)
    response = table.query(**query)
    while True:
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            return items
        response = table.query(**query, ExclusiveStartKey=response["LastEvaluatedKey"])


def _first_contact_tracking() -> tuple[datetime | None, dict[tuple[str, str, str], datetime]]:
    now = time.time()
    tracking_start, calls = _followup_call_tracking()
    if (_first_contact_cache.get("source_calls") is calls
            and now - _first_contact_cache["loaded_at"] < 30):
        return _first_contact_cache["tracking_start"], _first_contact_cache["contacts"]
    if tracking_start is None:
        return None, {}
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
    _first_contact_cache.update({"loaded_at": now, "tracking_start": tracking_start, "contacts": contacts, "source_calls": calls})
    return tracking_start, contacts


def _followup_call_tracking() -> tuple[datetime | None, list[dict]]:
    # Both queue endpoints arrive together. Share one history read, including
    # on a cold worker, instead of issuing duplicate paginated DynamoDB queries.
    with _call_tracking_lock:
        return _load_call_tracking()


def _load_call_tracking() -> tuple[datetime | None, list[dict]]:
    now = time.time()
    if _followup_calls_cache["loaded_at"] and now - _followup_calls_cache["loaded_at"] < 30:
        return _followup_calls_cache["tracking_start"], _followup_calls_cache["calls"]
    first_page = calls_table.query(
        IndexName=COMMUNICATION_TIMESTAMP_INDEX,
        KeyConditionExpression=Key("record_type").eq("call"),
        ScanIndexForward=True,
        Limit=1,
    )
    first_items = first_page.get("Items", [])
    if not first_items:
        _followup_calls_cache.update({"loaded_at": time.time(), "tracking_start": None, "calls": []})
        return None, []
    first_epoch = _epoch(first_items[0].get("timestamp"))
    calls = _query_since(calls_table, "call", int(first_epoch),
                         ("direction", "timestamp", "phone_number", "company_number"))
    outbound = [item for item in calls if str(item.get("direction") or "").strip().lower() == "outbound"]
    tracking_start = datetime.fromtimestamp(first_epoch, tz=timezone.utc)
    _followup_calls_cache.update({"loaded_at": time.time(), "tracking_start": tracking_start, "calls": outbound})
    return tracking_start, outbound


def _followup_message_tracking(tracking_start: datetime) -> list[dict]:
    now = time.time()
    cached_start = _followup_messages_cache["tracking_start"]
    if cached_start == tracking_start and now - _followup_messages_cache["loaded_at"] < 30:
        return _followup_messages_cache["messages"]
    since_epoch = int(tracking_start.timestamp())
    with ThreadPoolExecutor(max_workers=2) as executor:
        sms_future = executor.submit(_query_since, sms_messages_table, "message", since_epoch,
                                     ("direction", "sales_name", "company_name", "timestamp", "phone_number", "company_number", "number_id"))
        meta_future = executor.submit(_query_since, conversations_table, "message", since_epoch * 1000,
                                      ("role", "sales_name", "platform", "timestamp", "user_id", "page_id"))
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
    candidate_leads = (
        db.query(Lead)
        .options(*_queue_lead_options())
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
    # Messages older than every eligible lead cannot complete any attempt.
    # Avoid fetching message history at all when this queue has no candidates.
    messages = _followup_message_tracking(leads_with_created_at[-1][1]) if leads_with_created_at else []
    rows = calculate_followup_rows(leads_with_created_at, calls, messages, datetime.now(timezone.utc))
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
    rep: str = Query(""),
    company: str = Query(""),
    refresh: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if refresh:
        _first_contact_cache["loaded_at"] = 0.0
        _followup_calls_cache["loaded_at"] = 0.0
    tracking_start, contacts = _first_contact_tracking()
    if tracking_start is None:
        return {"items": [], "counts": {"new": 0, "overdue": 0}, "total": 0, "has_more": False, "tracking_start": ""}
    leads = (
        db.query(Lead)
        .options(*_queue_lead_options())
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
    global_counts = {name: len(rows) for name, rows in pending.items()}
    filtered_pending = {
        name: [lead for lead in rows if (not rep or (lead.assignee.name if lead.assignee else "Unassigned") == rep) and (not company or (lead.company.name if lead.company else "") == company)]
        for name, rows in pending.items()
    }
    selected = filtered_pending[category]
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
    counts = {name: len(rows) for name, rows in filtered_pending.items()}
    return {
        "items": items,
        "counts": counts,
        "global_counts": global_counts,
        "total": len(selected),
        "has_more": offset + limit < len(selected),
        "tracking_start": tracking_start.isoformat(),
    }


def _ignored_call_numbers(db: Session) -> dict[str, set[str]]:
    row = db.query(AppSetting).filter(AppSetting.key == IGNORED_CALL_NUMBERS_SETTING).first()
    if not row or not row.value:
        return {}
    try:
        values = json.loads(row.value)
    except (TypeError, ValueError):
        logger.warning("Invalid ignored call numbers setting")
        return {}
    ignored: dict[str, set[str]] = {}
    for value in values:
        if isinstance(value, dict):
            number = _digits(value.get("number"))
            direction = str(value.get("direction") or "both").strip().lower()
        else:
            number = _digits(value)
            direction = "both"
        if number and direction in {"from", "to", "both"}:
            ignored.setdefault(number, set()).add(direction)
    return ignored


def _save_ignored_call_numbers(db: Session, numbers: dict[str, set[str]]) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == IGNORED_CALL_NUMBERS_SETTING).first()
    entries = [
        {"number": number, "direction": direction}
        for number in sorted(numbers)
        for direction in sorted(numbers[number])
    ]
    value = json.dumps(entries, separators=(",", ":"))
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
    rep: str = Query(""),
    company: str = Query(""),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    states = (
        db.query(MissedCallState)
        .options(*_queue_lead_options(MissedCallState.lead))
        .order_by(MissedCallState.latest_missed_at.desc())
        .all()
    )
    ignored_numbers = _ignored_call_numbers(db)
    ignored_from = {number for number, directions in ignored_numbers.items() if directions & {"from", "both"}}
    ignored_to = {number for number, directions in ignored_numbers.items() if directions & {"to", "both"}}
    global_states = [
        state for state in states
        if _digits(state.client_identifier) not in ignored_from
        and _digits(state.company_identifier) not in ignored_to
    ]
    states = [
        state for state in global_states
        if (not rep or (state.lead.assignee.name if state.lead and state.lead.assignee else "Unassigned") == rep)
        and (not company or (state.lead.company.name if state.lead and state.lead.company else "") == company)
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
    return {"items": items, "count": len(states), "global_count": len(global_states)}


class MessageCleanupRequest(BaseModel):
    channel: str
    message_id: str


@router.post("/message-states/clean")
def clean_message_state(body: MessageCleanupRequest, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    from message_state_cleanup import latest_message
    state = db.get(MessageState, (body.channel, body.message_id))
    if state is None:
        return {"removed": 0, "result": "already_removed"}
    if state.conversation_ended:
        return {"removed": 0, "result": "manually_ended"}
    if state.channel not in {"sms", "messenger", "instagram"}:
        return {"removed": 0, "result": "unverified"}
    # Capture the exact state before network I/O; never delete a concurrently
    # replaced, reassigned or manually ended row based on this older snapshot.
    channel, message_id = state.channel, state.message_id
    client, company, occurred = state.client_identifier, state.company_identifier, state.occurred_at
    db.rollback()
    try:
        latest = latest_message(sms_messages_table if channel == "sms" else conversations_table,
                                channel, client, company)
    except (BotoCoreError, ClientError, TimeoutError, ValueError):
        logger.exception("Could not verify message state %s/%s", channel, message_id)
        return {"removed": 0, "result": "unverified"}
    normalized = occurred.replace(tzinfo=timezone.utc) if occurred.tzinfo is None else occurred
    if not latest or latest[1] == "unknown":
        return {"removed": 0, "result": "unverified"}
    if latest[1] != "outbound" or latest[0] <= normalized:
        return {"removed": 0, "result": "still_unanswered"}
    removed = db.query(MessageState).filter_by(channel=channel, message_id=message_id,
        client_identifier=client, company_identifier=company, occurred_at=occurred,
        conversation_ended=False).delete(synchronize_session=False)
    db.commit()
    if removed:
        publish_realtime_event({"type": "message_state_changed", "event_id": str(uuid.uuid4()),
            "action": "remove", "channel": channel, "message_ids": [message_id],
            "count_delta": {"unanswered": -removed, "ended": 0}})
    return {"removed": removed, "result": "answered" if removed else "changed_during_check"}


@router.get("/message-states/all")
def list_all_message_states(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return active states and the last 24 hours of ended history."""
    states = (
        db.query(MessageState)
        .filter(visible_message_states())
        .order_by(MessageState.occurred_at.desc(), MessageState.channel.asc(), MessageState.message_id.asc())
        .all()
    )
    return {
        "items": [
            {
                "channel": state.channel,
                "message_id": state.message_id,
                "lead_id": state.lead_id,
                "client_identifier": state.client_identifier,
                "company_identifier": state.company_identifier,
                "direction": state.direction,
                "conversation_ended": state.conversation_ended,
                "occurred_at": state.occurred_at.isoformat(),
            }
            for state in states
        ],
        "count": len(states),
    }


@router.get("/missed-call-states/all")
def list_all_missed_call_states(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the CRM missed-call state table exactly as stored, without side effects."""
    states = (
        db.query(MissedCallState)
        .order_by(MissedCallState.latest_missed_at.desc(), MissedCallState.client_identifier.asc())
        .all()
    )
    return {
        "items": [
            {
                "client_identifier": state.client_identifier,
                "company_identifier": state.company_identifier,
                "call_id": state.call_id,
                "lead_id": state.lead_id,
                "missed_count": state.missed_count,
                "first_missed_at": state.first_missed_at.isoformat(),
                "latest_missed_at": state.latest_missed_at.isoformat(),
            }
            for state in states
        ],
        "count": len(states),
    }


@router.get("/ignored-call-numbers")
def list_ignored_call_numbers(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    ignored = _ignored_call_numbers(db)
    return {"items": [
        {"number": number, "direction": direction}
        for number in sorted(ignored)
        for direction in sorted(ignored[number])
    ]}


@router.post("/ignored-call-numbers")
def add_ignored_call_number(
    body: IgnoredNumberRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    number = _digits(body.number)
    if len(number) < 7 or len(number) > 15:
        raise HTTPException(status_code=400, detail="Phone number must contain 7 to 15 digits")
    direction = body.direction.strip().lower()
    if direction not in {"from", "to", "both"}:
        raise HTTPException(status_code=400, detail="Direction must be from, to, or both")
    numbers = _ignored_call_numbers(db)
    if direction == "both":
        numbers[number] = {"both"}
    elif "both" not in numbers.get(number, set()):
        numbers.setdefault(number, set()).add(direction)
    _save_ignored_call_numbers(db, numbers)
    side_filter = (
        or_(MissedCallState.client_identifier == number, MissedCallState.company_identifier == number)
        if direction == "both"
        else MissedCallState.client_identifier == number
        if direction == "from"
        else MissedCallState.company_identifier == number
    )
    call_states = db.query(MissedCallState).filter(side_filter).all()
    call_ids = [state.call_id for state in call_states]
    for state in call_states:
        db.delete(state)
    message_side_filter = (
        or_(MessageState.client_identifier == number, MessageState.company_identifier == number)
        if direction == "both"
        else MessageState.client_identifier == number
        if direction == "from"
        else MessageState.company_identifier == number
    )
    message_states = db.query(MessageState).filter(MessageState.channel == "sms", message_side_filter).all()
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
    return {"items": [
        {"number": saved_number, "direction": saved_direction}
        for saved_number in sorted(numbers)
        for saved_direction in sorted(numbers[saved_number])
    ], "events": [call_event, message_event]}


@router.delete("/ignored-call-numbers/{number}")
def remove_ignored_call_number(
    number: str,
    direction: str = Query(""),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    normalized = _digits(number)
    numbers = _ignored_call_numbers(db)
    normalized_direction = direction.strip().lower()
    if normalized_direction in {"from", "to", "both"}:
        numbers.get(normalized, set()).discard(normalized_direction)
        if not numbers.get(normalized):
            numbers.pop(normalized, None)
    else:
        numbers.pop(normalized, None)
    _save_ignored_call_numbers(db, numbers)
    db.commit()
    return {"items": [
        {"number": saved_number, "direction": saved_direction}
        for saved_number in sorted(numbers)
        for saved_direction in sorted(numbers[saved_number])
    ]}


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
    rep: str = Query(""),
    company: str = Query(""),
    platform: str = Query(""),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    started_at = time.perf_counter()
    ignored_numbers = _ignored_call_numbers(db)
    ignored_from = {number for number, directions in ignored_numbers.items() if directions & {"from", "both"}}
    ignored_to = {number for number, directions in ignored_numbers.items() if directions & {"to", "both"}}
    global_visible_filter = visible_message_states()
    if ignored_numbers:
        global_visible_filter = and_(global_visible_filter, ~and_(
            MessageState.channel == "sms",
            or_(
                MessageState.client_identifier.in_(ignored_from) if ignored_from else False,
                MessageState.company_identifier.in_(ignored_to) if ignored_to else False,
            ),
        ))
    global_count_rows = (
        db.query(MessageState.conversation_ended, func.count())
        .filter(global_visible_filter)
        .group_by(MessageState.conversation_ended)
        .all()
    )
    global_counts_by_ended = {bool(value): int(count) for value, count in global_count_rows}
    visible_filter = global_visible_filter
    if platform:
        visible_filter = and_(visible_filter, MessageState.channel == platform.strip().lower())
    if rep:
        if rep == "Unassigned":
            visible_filter = and_(visible_filter, or_(MessageState.lead_id.is_(None), MessageState.lead.has(Lead.assigned_to.is_(None))))
        else:
            visible_filter = and_(visible_filter, MessageState.lead.has(Lead.assignee.has(User.name == rep)))
    if company:
        visible_filter = and_(visible_filter, MessageState.lead.has(Lead.company.has(Company.name == company)))
    count_rows = global_count_rows if not (rep or company or platform) else (
        db.query(MessageState.conversation_ended, func.count())
        .filter(visible_filter)
        .group_by(MessageState.conversation_ended)
        .all()
    )
    counts_by_ended = {bool(value): int(count) for value, count in count_rows}
    query = (
        db.query(MessageState)
        .options(*_queue_lead_options(MessageState.lead))
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
            "message": str(message.get("text") or "") if message else "Preview is being prepared",
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
        "global_counts": {"unanswered": global_counts_by_ended.get(False, 0), "ended": global_counts_by_ended.get(True, 0)},
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
    state.ended_at = datetime.now(timezone.utc) if body.ended else None
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
