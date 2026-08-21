"""Unified latest-message inbox across SMS, Messenger, and Instagram."""

import logging
import base64
import json
from datetime import datetime

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from db import conversations_table, sms_messages_table
from libs.common.phone import normalize_digits
from models import Company, Lead, User, UserCompany

logger = logging.getLogger("moving-crm")
router = APIRouter(prefix="/api/chats", tags=["Chats"])
DONE_CURSOR = {"__done": True}


def _user_company_ids(user: User, db: Session) -> list[str]:
    rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
    if rows:
        return [row[0] for row in rows]
    if user.role == "admin":
        return [row[0] for row in db.query(Company.id).all()]
    return []


def _scan_page(table, start_key: dict | None, limit: int) -> tuple[list[dict], dict | None]:
    kwargs: dict = {"Limit": limit}
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    response = table.scan(**kwargs)
    return response.get("Items", []), response.get("LastEvaluatedKey")


def _encode_cursor(meta_key: dict | None, sms_key: dict | None) -> str:
    payload = json.dumps(
        {"meta": meta_key, "sms": sms_key},
        separators=(",", ":"),
        default=lambda value: float(value),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[dict | None, dict | None]:
    if not cursor:
        return None, None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        return payload.get("meta"), payload.get("sms")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid chats cursor") from exc


def _timestamp(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _lead_time(lead: Lead) -> datetime:
    return lead.updated_at or lead.created_at or datetime.min


@router.get("")
def get_all_chats(
    cursor: str = Query(default=""),
    limit: int = Query(default=20, ge=2, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view all chats")

    company_ids = _user_company_ids(user, db)
    if not company_ids:
        return {"items": [], "next_cursor": "", "has_more": False}

    lead_query = db.query(Lead).filter(Lead.company_id.in_(company_ids))
    leads = lead_query.all()

    meta_leads: dict[str, Lead] = {}
    sms_leads: dict[tuple[str, str], Lead] = {}
    sms_phone_leads: dict[str, list[Lead]] = {}
    for lead in leads:
        if lead.facebook_user_id:
            current = meta_leads.get(lead.facebook_user_id)
            if current is None or _lead_time(lead) > _lead_time(current):
                meta_leads[lead.facebook_user_id] = lead
        phone = normalize_digits(lead.phone or "")
        if len(phone) == 11 and phone.startswith("1"):
            phone = phone[1:]
        if phone:
            company_name = (lead.company.name if lead.company else "").strip().lower()
            sms_key = (phone, company_name)
            current = sms_leads.get(sms_key)
            if current is None or _lead_time(lead) > _lead_time(current):
                sms_leads[sms_key] = lead
            sms_phone_leads.setdefault(phone, []).append(lead)

    try:
        meta_start, sms_start = _decode_cursor(cursor)
        meta_limit = (limit + 1) // 2
        sms_limit = limit // 2
        if meta_start == DONE_CURSOR:
            meta_messages, meta_next = [], None
            meta_done = True
        else:
            meta_messages, meta_next = _scan_page(conversations_table, meta_start, meta_limit)
            meta_done = meta_next is None
        if sms_start == DONE_CURSOR:
            sms_messages, sms_next = [], None
            sms_done = True
        else:
            sms_messages, sms_next = _scan_page(sms_messages_table, sms_start, sms_limit)
            sms_done = sms_next is None
    except ClientError as exc:
        logger.error("Could not load unified chats: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch chats") from exc

    latest: dict[tuple[str, str], dict] = {}

    def add_message(lead: Lead, platform: str, message: dict) -> None:
        timestamp = _timestamp(message.get("timestamp"))
        key = (lead.id, platform)
        if key in latest and latest[key]["timestamp"] >= timestamp:
            return
        latest[key] = {
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "rep": lead.assignee.name if lead.assignee else "",
            "platform": platform,
            "message": str(message.get("text") or ""),
            "timestamp": timestamp,
            "direction": str(message.get("direction") or message.get("role") or ""),
        }

    for message in meta_messages:
        platform = str(message.get("platform") or "").strip().lower()
        if platform not in {"messenger", "instagram"}:
            continue
        lead = meta_leads.get(str(message.get("user_id") or ""))
        if lead:
            add_message(lead, platform, message)

    for message in sms_messages:
        phone = normalize_digits(str(message.get("phone_number") or ""))
        if len(phone) == 11 and phone.startswith("1"):
            phone = phone[1:]
        company_name = str(message.get("company_name") or "").strip().lower()
        lead = sms_leads.get((phone, company_name))
        if lead is None:
            phone_matches = sms_phone_leads.get(phone, [])
            if len(phone_matches) == 1:
                lead = phone_matches[0]
        if lead:
            add_message(lead, "sms", message)

    has_more = not meta_done or not sms_done
    return {
        "items": sorted(latest.values(), key=lambda item: item["timestamp"], reverse=True),
        "next_cursor": _encode_cursor(
            meta_next if not meta_done else DONE_CURSOR,
            sms_next if not sms_done else DONE_CURSOR,
        ) if has_more else "",
        "has_more": has_more,
    }
