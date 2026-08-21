"""Admin response monitoring and webhook-fed communication state."""

import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from config import get_config
from database import get_db
from models import Lead, LeadCommunicationState, User

router = APIRouter(prefix="/api/rep-activity", tags=["Rep Activity"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _latest(current: datetime | None, incoming: datetime) -> datetime:
    return incoming if current is None or incoming > _aware(current) else current


class CommunicationUpdate(BaseModel):
    lead_id: str
    channel: Literal["sms", "messenger", "instagram", "call"]
    direction: Literal["inbound", "outbound"]
    occurred_at: datetime
    answered: bool | None = None


@router.post("/communication-update")
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
    category: str = Query(default="new", pattern="^(new|no_first_contact|unanswered|missed_calls)$"),
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

    if category == "new":
        order = Lead.created_at.desc()
    elif category == "no_first_contact":
        order = Lead.created_at.asc()
    elif category == "unanswered":
        order = LeadCommunicationState.latest_inbound_message_at.asc()
    else:
        order = LeadCommunicationState.latest_missed_call_at.asc()

    rows = (
        queries[category]
        .options(joinedload(Lead.company), joinedload(Lead.assignee), joinedload(Lead.communication_state))
        .order_by(order)
        .offset(offset)
        .limit(limit)
        .all()
    )
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
        items.append({
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "rep": lead.assignee.name if lead.assignee else "",
            "company": lead.company.name if lead.company else "",
            "created_at": lead.created_at.isoformat() if lead.created_at else "",
            "age_minutes": age_minutes,
            "status": lead.status or "new",
        })

    total = counts[category]
    return {"counts": counts, "items": items, "total": total, "has_more": offset + limit < total}
