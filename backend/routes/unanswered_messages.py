"""Admin-only API for the new Unanswered Messages page."""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from auth import require_admin
from database import get_db
from db import conversations_table, sms_messages_table
from models import Company, Lead, MessageState, User
from realtime import publish_realtime_event

router = APIRouter(prefix="/api/unanswered-messages", tags=["Unanswered Messages"])
logger = logging.getLogger("moving-crm")


class EndStateRequest(BaseModel):
    channel: str
    message_id: str
    ended: bool


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
    limit: int = Query(50, ge=1, le=100),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    started_at = time.perf_counter()
    all_states = (
        db.query(MessageState)
        .options(joinedload(MessageState.lead).joinedload(Lead.company), joinedload(MessageState.lead).joinedload(Lead.assignee))
        .order_by(MessageState.occurred_at.desc())
        .all()
    )
    sql_finished_at = time.perf_counter()
    unanswered_count = sum(not state.conversation_ended for state in all_states)
    ended_count = len(all_states) - unanswered_count
    states = [state for state in all_states if bool(state.conversation_ended) is ended][:limit]
    messages = _preview_messages(states)
    previews_finished_at = time.perf_counter()
    page_ids = {state.company_identifier for state in states if state.channel != "sms" and not state.lead_id}
    companies_by_page = {
        company.facebook_page_id: company.name
        for company in db.query(Company).filter(Company.facebook_page_id.in_(page_ids)).all()
    } if page_ids else {}
    items = []
    for state in states:
        lead = state.lead
        message = messages.get((state.channel, state.message_id), {})
        items.append({
            "channel": state.channel,
            "message_id": state.message_id,
            "lead_id": state.lead_id or "",
            "client": lead.full_name if lead else state.client_identifier,
            "message": str(message.get("text") or ""),
            "rep": lead.assignee.name if lead and lead.assignee else "Unassigned",
            "company": (
                lead.company.name if lead and lead.company
                else companies_by_page.get(state.company_identifier, str(message.get("company_name") or ""))
            ),
            "occurred_at": state.occurred_at.isoformat(),
        })
    logger.info(
        "Unanswered messages load total_rows=%d displayed_rows=%d sql_ms=%.1f previews_ms=%.1f total_ms=%.1f",
        len(all_states),
        len(states),
        (sql_finished_at - started_at) * 1000,
        (previews_finished_at - sql_finished_at) * 1000,
        (time.perf_counter() - started_at) * 1000,
    )
    return {"items": items, "counts": {"unanswered": unanswered_count, "ended": ended_count}}


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
