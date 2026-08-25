"""Admin-only API for the new Unanswered Messages page."""

import base64
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from auth import require_admin
from database import get_db
from db import conversations_table, sms_messages_table
from models import AppSetting, Company, Lead, MessageState, MissedCallState, User
from realtime import publish_realtime_event

router = APIRouter(prefix="/api/unanswered-messages", tags=["Unanswered Messages"])
logger = logging.getLogger("moving-crm")
IGNORED_CALL_NUMBERS_SETTING = "sales_work_queue.ignored_call_numbers"


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
    if item.get("text") is not None:
        return item
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
            "client": lead.full_name if lead else state.client_identifier,
            "client_number": _digits(state.client_identifier) if state.channel == "sms" else "",
            "message": str(message.get("text") or ""),
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
        "client": lead.full_name if lead else state.client_identifier,
        "message": str(message.get("text") or ""),
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
