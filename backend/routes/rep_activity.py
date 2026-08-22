"""Admin response monitoring and webhook-fed communication state."""

import hmac
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from config import get_config
from database import get_db
from db import conversations_table, sms_messages_table
from libs.common.phone import phone_variants
from models import Lead, LeadCommunicationState, User

router = APIRouter(prefix="/api/rep-activity", tags=["Rep Activity"])
lead_activity_router = APIRouter(prefix="/api/lead-activity", tags=["Lead Activity"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _latest(current: datetime | None, incoming: datetime) -> datetime:
    return incoming if current is None or incoming > _aware(current) else current


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
                "age_minutes": max(0, int((now - occurred_at).total_seconds() // 60)),
                "status": "Closed",
                "platform": chat.get("platform") or "",
                "message": chat.get("message") or "",
                "latest_message_at": occurred_at.isoformat(),
                "message_partition_key": chat.get("message_partition_key") or "",
                "message_timestamp": chat.get("message_timestamp"),
            })
    return sorted(items, key=lambda item: item["age_minutes"])


class CommunicationUpdate(BaseModel):
    lead_id: str
    channel: Literal["sms", "messenger", "instagram", "call"]
    direction: Literal["inbound", "outbound"]
    occurred_at: datetime
    answered: bool | None = None


class EndConversationRequest(BaseModel):
    platform: Literal["sms", "messenger", "instagram"]
    partition_key: str
    timestamp: int | float


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
    table.update_item(
        Key={partition_name: partition_key, "timestamp": Decimal(str(body.timestamp))},
        UpdateExpression="SET conversation_ended = :ended",
        ExpressionAttributeValues={":ended": True},
    )
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

    lead = db.query(Lead).filter(Lead.id == body.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    occurred_at = _aware(body.occurred_at)
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
    return {"ok": True, "lead_id": lead.id}


@router.get("")
def get_rep_activity(
    category: str = Query(default="new", pattern="^(new|no_first_contact|unanswered|missed_calls|closed_chats)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view rep activity")

    now = _utcnow()
    cutoff = now - timedelta(minutes=30)
    base_query = db.query(Lead).outerjoin(LeadCommunicationState, LeadCommunicationState.lead_id == Lead.id)
    no_contact = or_(LeadCommunicationState.lead_id.is_(None), LeadCommunicationState.first_contact_at.is_(None))
    new_query = base_query.filter(Lead.created_at > cutoff, no_contact)
    no_contact_query = base_query.filter(Lead.created_at <= cutoff, no_contact)
    unanswered_query = base_query.filter(
        LeadCommunicationState.latest_inbound_message_at.isnot(None),
        or_(
            LeadCommunicationState.latest_outbound_message_at.is_(None),
            LeadCommunicationState.latest_inbound_message_at > LeadCommunicationState.latest_outbound_message_at,
        ),
    )
    missed_query = base_query.filter(
        LeadCommunicationState.latest_missed_call_at.isnot(None),
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
    unmatched_items = _unmatched_unanswered(user, db, now) if category == "unanswered" else []
    closed_items = _closed_chats(user, db, now)
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
        message_record = _latest_message_record(lead, state.latest_message_channel) if category == "unanswered" and state else {}
        if category == "unanswered" and message_record.get("conversation_ended"):
            continue
        items.append({
            "conversation_id": f"lead:{lead.id}",
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "rep": lead.assignee.name if lead.assignee else "",
            "company": lead.company.name if lead.company else "",
            "created_at": lead.created_at.isoformat() if lead.created_at else "",
            "age_minutes": age_minutes,
            "status": lead.status or "new",
            "platform": state.latest_message_channel if category == "unanswered" and state else "",
            "message": str(message_record.get("text") or "").strip(),
            "latest_message_at": reference_at.isoformat() if category == "unanswered" and reference_at else "",
            "message_partition_key": str(message_record.get("phone_number") or message_record.get("user_id") or ""),
            "message_timestamp": message_record.get("timestamp"),
        })

    if category == "unanswered":
        items.extend(unmatched_items)
        items.sort(key=lambda item: item["age_minutes"], reverse=True)
        counts["unanswered"] = len(items)
        items = items[offset:offset + limit]

    total = counts[category]
    return {"counts": counts, "items": items, "total": total, "has_more": offset + limit < total}
