"""Admin response monitoring and webhook-fed communication state."""

import hmac
import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from config import get_config
from database import get_db
from db import conversations_table, sms_messages_table
from libs.common.phone import normalize_digits, phone_variants
from models import AppSetting, Lead, LeadCommunicationState, User
from realtime import publish_realtime_event

router = APIRouter(prefix="/api/rep-activity", tags=["Rep Activity"])
lead_activity_router = APIRouter(prefix="/api/lead-activity", tags=["Lead Activity"])
logger = logging.getLogger("moving-crm")
IGNORED_NUMBERS_SETTING = "rep_activity.ignored_sms_numbers"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _latest(current: datetime | None, incoming: datetime) -> datetime:
    return incoming if current is None or incoming > _aware(current) else current


def _normalized_number(value: str) -> str:
    digits = normalize_digits(value)
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def _ignored_sms_numbers(db: Session) -> set[str]:
    row = db.query(AppSetting).filter(AppSetting.key == IGNORED_NUMBERS_SETTING).first()
    if not row or not row.value:
        return set()
    try:
        values = json.loads(row.value)
    except (TypeError, ValueError):
        logger.warning("Invalid ignored SMS numbers setting")
        return set()
    return {_normalized_number(str(value)) for value in values if _normalized_number(str(value))}


def _latest_message_record(lead: Lead, channel: str) -> dict:
    """Read the latest inbound message text from the channel's DynamoDB table."""
    try:
        if channel == "sms" and lead.phone:
            allowed_number_ids = {
                str(value).strip()
                for value in (
                    lead.assignee.aircall_number_id if lead.assignee else "",
                    lead.company.aircall_number_id if lead.company else "",
                )
                if value
            }
            newest: dict | None = None
            for phone in phone_variants(lead.phone):
                kwargs = {
                    "KeyConditionExpression": Key("phone_number").eq(phone),
                    "ScanIndexForward": False,
                    "Limit": 20,
                }
                while True:
                    response = sms_messages_table.query(**kwargs)
                    for message in response.get("Items", []):
                        if str(message.get("direction") or "").lower() != "received":
                            continue
                        if str(message.get("number_id") or "").strip() not in allowed_number_ids:
                            continue
                        if newest is None or float(message.get("timestamp") or 0) > float(newest.get("timestamp") or 0):
                            newest = message
                    if newest is not None or "LastEvaluatedKey" not in response:
                        break
                    kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            return newest or {}

        if channel in {"messenger", "instagram"} and lead.facebook_user_id:
            kwargs = {
                "KeyConditionExpression": Key("user_id").eq(lead.facebook_user_id),
                "FilterExpression": Attr("platform").eq(channel) & Attr("role").eq("user"),
                "ScanIndexForward": False,
                "Limit": 20,
            }
            while True:
                response = conversations_table.query(**kwargs)
                messages = response.get("Items", [])
                if messages:
                    return messages[0]
                if "LastEvaluatedKey" not in response:
                    break
                kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    except (ClientError, TypeError, ValueError):
        return {}
    return {}


def _unmatched_unanswered(user: User, db: Session, now: datetime) -> list[dict]:
    from routes.chats import get_all_chats

    items: list[dict] = []
    for source in ("sms", "meta"):
        chats = get_all_chats(cursor="", limit=100, source=source, user=user, db=db)
        for chat in chats["items"]:
            if chat.get("lead_id"):
                continue
            if chat.get("conversation_ended"):
                continue
            direction = str(chat.get("direction") or "").lower()
            if direction not in {"received", "inbound", "user"}:
                continue
            occurred_at = datetime.fromtimestamp(float(chat.get("timestamp") or 0), tz=timezone.utc)
            items.append({
                "conversation_id": chat.get("conversation_id") or "",
                "lead_id": "",
                "client": chat.get("client") or "Unknown client",
                "rep": chat.get("rep") or "",
                "company": chat.get("company") or "",
                "created_at": occurred_at.isoformat(),
                "reference_at": occurred_at.isoformat(),
                "age_minutes": max(0, int((now - occurred_at).total_seconds() // 60)),
                "status": "Unmatched",
                "platform": chat.get("platform") or "",
                "message": chat.get("message") or "",
                "latest_message_at": occurred_at.isoformat(),
                "message_partition_key": chat.get("message_partition_key") or "",
                "message_timestamp": chat.get("message_timestamp"),
            })
    return items


def _closed_chats(user: User, db: Session, now: datetime) -> list[dict]:
    from routes.chats import get_all_chats

    items: list[dict] = []
    for source in ("sms", "meta"):
        chats = get_all_chats(cursor="", limit=100, source=source, user=user, db=db)
        for chat in chats["items"]:
            if not chat.get("conversation_ended"):
                continue
            occurred_at = datetime.fromtimestamp(float(chat.get("timestamp") or 0), tz=timezone.utc)
            items.append({
                "conversation_id": chat.get("conversation_id") or "",
                "lead_id": chat.get("lead_id") or "",
                "client": chat.get("client") or "Unknown client",
                "rep": chat.get("rep") or "",
                "company": chat.get("company") or "",
                "created_at": occurred_at.isoformat(),
                "reference_at": occurred_at.isoformat(),
                "age_minutes": max(0, int((now - occurred_at).total_seconds() // 60)),
                "status": "Closed",
                "platform": chat.get("platform") or "",
                "message": chat.get("message") or "",
                "latest_message_at": occurred_at.isoformat(),
                "message_partition_key": chat.get("message_partition_key") or "",
                "message_timestamp": chat.get("message_timestamp"),
            })
    return sorted(items, key=lambda item: item["age_minutes"])


def _conversation_activity(user: User, db: Session, now: datetime, range_start: datetime, range_end: datetime, ignored_numbers: set[str]) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Build activity lists and latest linked messages from one fetch per platform."""
    from routes.chats import get_all_chats

    unmatched: list[dict] = []
    closed: list[dict] = []
    linked_latest: dict[str, dict] = {}
    for source in ("sms", "meta"):
        chats = get_all_chats(cursor="", limit=100, source=source, user=user, db=db)
        for chat in chats["items"]:
            occurred_at = datetime.fromtimestamp(float(chat.get("timestamp") or 0), tz=timezone.utc)
            if occurred_at < range_start or occurred_at >= range_end:
                continue
            item = {
                "conversation_id": chat.get("conversation_id") or "",
                "lead_id": chat.get("lead_id") or "",
                "client": chat.get("client") or "Unknown client",
                "rep": chat.get("rep") or "",
                "company": chat.get("company") or "",
                "created_at": occurred_at.isoformat(),
                "age_minutes": max(0, int((now - occurred_at).total_seconds() // 60)),
                "platform": chat.get("platform") or "",
                "message": chat.get("message") or "",
                "latest_message_at": occurred_at.isoformat(),
                "message_partition_key": chat.get("message_partition_key") or "",
                "message_timestamp": chat.get("message_timestamp"),
            }
            lead_id = str(chat.get("lead_id") or "")
            if lead_id:
                current = linked_latest.get(lead_id)
                if current is None or item["created_at"] > current["created_at"]:
                    linked_latest[lead_id] = {**item, "conversation_ended": bool(chat.get("conversation_ended"))}
            if chat.get("conversation_ended"):
                closed.append({**item, "status": "Closed"})
                continue
            if str(chat.get("platform") or "").lower() == "sms" and _normalized_number(item["message_partition_key"]) in ignored_numbers:
                continue
            direction = str(chat.get("direction") or "").lower()
            if not chat.get("lead_id") and direction in {"received", "inbound", "user"}:
                unmatched.append({**item, "status": "Unmatched"})
    closed.sort(key=lambda item: item["age_minutes"])
    return unmatched, closed, linked_latest


class CommunicationUpdate(BaseModel):
    lead_id: str = ""
    channel: Literal["sms", "messenger", "instagram", "call"]
    direction: Literal["inbound", "outbound"]
    occurred_at: datetime
    answered: bool | None = None


class EndConversationRequest(BaseModel):
    platform: Literal["sms", "messenger", "instagram"]
    partition_key: str
    timestamp: int | float


class IgnoredNumbersUpdate(BaseModel):
    numbers: list[str]


@router.get("/ignored-numbers")
def get_ignored_numbers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can manage ignored numbers")
    return {"numbers": sorted(_ignored_sms_numbers(db))}


@router.put("/ignored-numbers")
def update_ignored_numbers(body: IgnoredNumbersUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can manage ignored numbers")
    numbers = sorted({_normalized_number(value) for value in body.numbers if _normalized_number(value)})
    if any(len(value) < 7 or len(value) > 15 for value in numbers):
        raise HTTPException(status_code=400, detail="Each phone number must contain 7 to 15 digits")
    row = db.query(AppSetting).filter(AppSetting.key == IGNORED_NUMBERS_SETTING).first()
    serialized = json.dumps(numbers, separators=(",", ":"))
    if row:
        row.value = serialized
    else:
        db.add(AppSetting(key=IGNORED_NUMBERS_SETTING, value=serialized))
    db.commit()
    return {"numbers": numbers}


@router.post("/conversations/end")
def end_conversation(
    body: EndConversationRequest,
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can end conversations")
    partition_key = body.partition_key.strip()
    if not partition_key:
        raise HTTPException(status_code=400, detail="partition_key is required")
    table = sms_messages_table if body.platform == "sms" else conversations_table
    partition_name = "phone_number" if body.platform == "sms" else "user_id"
    try:
        table.update_item(
            Key={partition_name: partition_key, "timestamp": Decimal(str(body.timestamp))},
            UpdateExpression="SET conversation_ended = :ended",
            ExpressionAttributeValues={":ended": True},
            ConditionExpression=f"attribute_exists({partition_name}) AND attribute_exists(#ts)",
            ExpressionAttributeNames={"#ts": "timestamp"},
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = str(error.get("Code") or "DynamoDBError")
        message = str(error.get("Message") or "Could not update the message")
        logger.exception("Could not mark conversation ended: %s: %s", code, message)
        if code == "ConditionalCheckFailedException":
            raise HTTPException(status_code=404, detail="Message record was not found") from exc
        raise HTTPException(status_code=502, detail=f"Could not mark conversation ended ({code}): {message}") from exc
    except (BotoCoreError, ValueError) as exc:
        logger.exception("Could not mark conversation ended")
        raise HTTPException(status_code=502, detail=f"Could not mark conversation ended: {exc}") from exc
    publish_realtime_event({
        "type": "communication_updated",
        "lead_id": "",
        "channel": body.platform,
        "direction": "ended",
        "occurred_at": _utcnow().isoformat(),
    })
    return {"ok": True}


@lead_activity_router.post("/communication-update")
def update_communication_state(
    body: CommunicationUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    secret = get_config().get("API_SECRET", os.getenv("API_SECRET", ""))
    provided = request.headers.get("x-api-secret", "")
    if not secret:
        raise HTTPException(status_code=500, detail="API secret not configured")
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Invalid API secret")
    if body.channel == "call" and body.answered is None:
        raise HTTPException(status_code=400, detail="answered is required for call updates")

    occurred_at = _aware(body.occurred_at)
    lead_id = body.lead_id.strip()
    if not lead_id:
        publish_realtime_event({
            "type": "communication_updated",
            "lead_id": "",
            "channel": body.channel,
            "direction": body.direction,
            "occurred_at": occurred_at.isoformat(),
        })
        return {"ok": True, "lead_id": ""}

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    state = db.query(LeadCommunicationState).filter(LeadCommunicationState.lead_id == lead.id).first()
    if state is None:
        state = LeadCommunicationState(lead_id=lead.id)
        db.add(state)

    if body.channel == "call":
        if body.direction == "inbound" and body.answered is False:
            state.latest_missed_call_at = _latest(state.latest_missed_call_at, occurred_at)
        else:
            state.latest_call_response_at = _latest(state.latest_call_response_at, occurred_at)
            if state.first_contact_at is None or occurred_at < _aware(state.first_contact_at):
                state.first_contact_at = occurred_at
    elif body.direction == "inbound":
        state.latest_inbound_message_at = _latest(state.latest_inbound_message_at, occurred_at)
        state.latest_message_channel = body.channel
    else:
        state.latest_outbound_message_at = _latest(state.latest_outbound_message_at, occurred_at)
        state.latest_message_channel = body.channel

    db.commit()
    publish_realtime_event({
        "type": "communication_updated",
        "lead_id": lead.id,
        "channel": body.channel,
        "direction": body.direction,
        "occurred_at": occurred_at.isoformat(),
    })
    return {"ok": True, "lead_id": lead.id}


@router.get("")
def get_rep_activity(
    category: str = Query(default="new", pattern="^(new|no_first_contact|unanswered|missed_calls|closed_chats)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view rep activity")

    now = _utcnow()
    eastern = ZoneInfo("America/New_York")
    eastern_today = now.astimezone(eastern).date()
    selected_start = start_date or (eastern_today - timedelta(days=3))
    selected_end = end_date or eastern_today
    if selected_end < selected_start:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    range_start = datetime.combine(selected_start, time.min, tzinfo=eastern).astimezone(timezone.utc)
    range_end = datetime.combine(selected_end + timedelta(days=1), time.min, tzinfo=eastern).astimezone(timezone.utc)
    cutoff = now - timedelta(minutes=30)
    base_query = db.query(Lead).outerjoin(LeadCommunicationState, LeadCommunicationState.lead_id == Lead.id)
    no_contact = or_(LeadCommunicationState.lead_id.is_(None), LeadCommunicationState.first_contact_at.is_(None))
    new_query = base_query.filter(Lead.created_at > cutoff, Lead.created_at >= range_start, Lead.created_at < range_end, no_contact)
    no_contact_query = base_query.filter(Lead.created_at <= cutoff, Lead.created_at >= range_start, Lead.created_at < range_end, no_contact)
    unanswered_query = base_query.filter(
        LeadCommunicationState.latest_inbound_message_at.isnot(None),
        LeadCommunicationState.latest_inbound_message_at >= range_start,
        LeadCommunicationState.latest_inbound_message_at < range_end,
        or_(
            LeadCommunicationState.latest_outbound_message_at.is_(None),
            LeadCommunicationState.latest_inbound_message_at > LeadCommunicationState.latest_outbound_message_at,
        ),
    )
    missed_query = base_query.filter(
        LeadCommunicationState.latest_missed_call_at.isnot(None),
        LeadCommunicationState.latest_missed_call_at >= range_start,
        LeadCommunicationState.latest_missed_call_at < range_end,
        or_(
            LeadCommunicationState.latest_call_response_at.is_(None),
            LeadCommunicationState.latest_missed_call_at > LeadCommunicationState.latest_call_response_at,
        ),
    )
    queries = {
        "new": new_query,
        "no_first_contact": no_contact_query,
        "unanswered": unanswered_query,
        "missed_calls": missed_query,
    }
    counts = {key: query.count() for key, query in queries.items()}
    ignored_numbers = _ignored_sms_numbers(db)
    unmatched_items, closed_items, linked_latest = _conversation_activity(user, db, now, range_start, range_end, ignored_numbers)
    closed_linked_count = sum(1 for item in closed_items if item.get("lead_id"))
    counts["unanswered"] = max(0, counts["unanswered"] + len(unmatched_items) - closed_linked_count)
    counts["closed_chats"] = len(closed_items)

    if category == "closed_chats":
        total = len(closed_items)
        return {
            "counts": counts,
            "items": closed_items[offset:offset + limit],
            "total": total,
            "has_more": offset + limit < total,
        }

    if category == "new":
        order = Lead.created_at.desc()
    elif category == "no_first_contact":
        order = Lead.created_at.asc()
    elif category == "unanswered":
        order = LeadCommunicationState.latest_inbound_message_at.asc()
    else:
        order = LeadCommunicationState.latest_missed_call_at.asc()

    rows_query = (
        queries[category]
        .options(joinedload(Lead.company), joinedload(Lead.assignee), joinedload(Lead.communication_state))
        .order_by(order)
    )
    rows = rows_query.all() if category == "unanswered" else rows_query.offset(offset).limit(limit).all()
    items = []
    for lead in rows:
        state = lead.communication_state
        reference_at = lead.created_at
        if category == "unanswered" and state:
            reference_at = state.latest_inbound_message_at
        elif category == "missed_calls" and state:
            reference_at = state.latest_missed_call_at
        reference_at = _aware(reference_at) if reference_at else None
        age_minutes = max(0, int((now - reference_at).total_seconds() // 60)) if reference_at else 0
        message_record = linked_latest.get(lead.id, {}) if category == "unanswered" else {}
        if category == "unanswered" and state and state.latest_message_channel == "sms" and _normalized_number(lead.phone or "") in ignored_numbers:
            continue
        if category == "unanswered" and message_record.get("conversation_ended"):
            continue
        items.append({
            "conversation_id": f"lead:{lead.id}",
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "rep": lead.assignee.name if lead.assignee else "",
            "company": lead.company.name if lead.company else "",
            "created_at": lead.created_at.isoformat() if lead.created_at else "",
            "reference_at": reference_at.isoformat() if reference_at else "",
            "age_minutes": age_minutes,
            "status": lead.status or "new",
            "platform": state.latest_message_channel if category == "unanswered" and state else "",
            "message": str(message_record.get("message") or "").strip(),
            "latest_message_at": reference_at.isoformat() if category == "unanswered" and reference_at else "",
            "message_partition_key": str(message_record.get("message_partition_key") or ""),
            "message_timestamp": message_record.get("message_timestamp"),
        })

    if category == "unanswered":
        items.extend(unmatched_items)
        items.sort(key=lambda item: item["age_minutes"], reverse=True)
        counts["unanswered"] = len(items)
        items = items[offset:offset + limit]

    total = counts[category]
    return {"counts": counts, "items": items, "total": total, "has_more": offset + limit < total}
