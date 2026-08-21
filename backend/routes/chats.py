"""Unified latest-message inbox across SMS, Messenger, and Instagram."""

import logging
from datetime import datetime

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from db import conversations_table, sms_messages_table
from libs.common.phone import normalize_digits
from models import Company, Lead, User, UserCompany

logger = logging.getLogger("moving-crm")
router = APIRouter(prefix="/api/chats", tags=["Chats"])


def _user_company_ids(user: User, db: Session) -> list[str]:
    rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
    if rows:
        return [row[0] for row in rows]
    if user.role == "admin":
        return [row[0] for row in db.query(Company.id).all()]
    return []


def _scan_all(table) -> list[dict]:
    items: list[dict] = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return items


def _timestamp(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _lead_time(lead: Lead) -> datetime:
    return lead.updated_at or lead.created_at or datetime.min


@router.get("")
def get_all_chats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view all chats")

    company_ids = _user_company_ids(user, db)
    if not company_ids:
        return {"items": []}

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
        meta_messages = _scan_all(conversations_table)
        sms_messages = _scan_all(sms_messages_table)
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

    return {"items": sorted(latest.values(), key=lambda item: item["timestamp"], reverse=True)}
