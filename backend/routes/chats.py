"""Unified latest-message inbox across SMS, Messenger, and Instagram."""

import logging
import base64
import json
from datetime import datetime

from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from database import get_db
from db import conversations_table, sms_messages_table
from libs.common.phone import normalize_digits
from models import Company, Lead, User, UserCompany

logger = logging.getLogger("moving-crm")
router = APIRouter(prefix="/api/chats", tags=["Chats"])
DONE_CURSOR = {"__done": True}
SMS_TIMESTAMP_INDEX = "record-type-timestamp-index"


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


def _query_sms_page(start_key: dict | None, limit: int) -> tuple[list[dict], dict | None]:
    kwargs: dict = {
        "IndexName": SMS_TIMESTAMP_INDEX,
        "KeyConditionExpression": Key("record_type").eq("message"),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    response = sms_messages_table.query(**kwargs)
    return response.get("Items", []), response.get("LastEvaluatedKey")


def _encode_cursor(meta_key: dict | None, sms_key: dict | None) -> str:
    # DynamoDB pagination keys can contain Decimal values. Serializing through
    # DynamoDB's typed format preserves them for ExclusiveStartKey on the next page.
    typed = TypeSerializer().serialize({"meta": meta_key, "sms": sms_key})
    payload = json.dumps(typed, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[dict | None, dict | None]:
    if not cursor:
        return None, None
    try:
        padding = "=" * (-len(cursor) % 4)
        typed = json.loads(base64.urlsafe_b64decode(cursor + padding))
        payload = TypeDeserializer().deserialize(typed)
        return payload.get("meta"), payload.get("sms")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid chats cursor") from exc


def _timestamp(value) -> float:
    try:
        timestamp = float(value or 0)
        # Meta records may use milliseconds while SMS records use seconds.
        # Normalize both to epoch seconds before comparing across platforms.
        return timestamp / 1000 if timestamp >= 1_000_000_000_000 else timestamp
    except (TypeError, ValueError):
        return 0


def _lead_time(lead: Lead) -> datetime:
    return lead.updated_at or lead.created_at or datetime.min


@router.get("")
def get_all_chats(
    cursor: str = Query(default=""),
    limit: int = Query(default=20, ge=2, le=100),
    source: str = Query(default="meta", pattern="^(meta|sms)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view all chats")

    company_ids = _user_company_ids(user, db)
    if not company_ids:
        return {"items": [], "next_cursor": "", "has_more": False}

    try:
        meta_start, sms_start = _decode_cursor(cursor)
        if source == "meta":
            sms_start = DONE_CURSOR
        else:
            meta_start = DONE_CURSOR
        meta_done = meta_start == DONE_CURSOR
        sms_done = sms_start == DONE_CURSOR
        meta_next = None if meta_done else meta_start
        sms_next = None if sms_done else sms_start
        meta_messages: list[dict] = []
        sms_messages: list[dict] = []
        conversation_keys: set[tuple[str, str, str]] = set()

        # A page means unique conversations, not raw messages. Keep advancing
        # through full raw-message batches until the requested minimum is
        # collected. Return every conversation found in the final batch so a
        # scanned conversation is never discarded merely to enforce the limit.
        while len(conversation_keys) < limit and not (meta_done and sms_done):
            active_sources = int(not meta_done) + int(not sms_done)
            meta_limit = 0
            sms_limit = 0
            if not meta_done:
                meta_limit = limit if active_sources == 1 else (limit + 1) // 2
            if not sms_done:
                sms_limit = limit if active_sources == 1 else limit // 2

            if meta_limit:
                page, meta_next = _scan_page(conversations_table, meta_next, meta_limit)
                meta_messages.extend(page)
                for message in page:
                    platform = str(message.get("platform") or "").strip().lower()
                    user_id = str(message.get("user_id") or "")
                    if platform in {"messenger", "instagram"} and user_id:
                        conversation_keys.add(("meta", user_id, platform))
                meta_done = meta_next is None

            if sms_limit:
                page, sms_next = _query_sms_page(sms_next, sms_limit)
                sms_messages.extend(page)
                for message in page:
                    phone = normalize_digits(str(message.get("phone_number") or ""))
                    if len(phone) == 11 and phone.startswith("1"):
                        phone = phone[1:]
                    if phone:
                        company_name = str(message.get("company_name") or "").strip().lower()
                        conversation_keys.add(("sms", phone, company_name))
                sms_done = sms_next is None
    except ClientError as exc:
        logger.error("Could not load unified chats: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch chats") from exc

    meta_user_ids = {
        str(message.get("user_id") or "")
        for message in meta_messages
        if message.get("user_id")
    }
    sms_phones: set[str] = set()
    for message in sms_messages:
        phone = normalize_digits(str(message.get("phone_number") or ""))
        if len(phone) == 11 and phone.startswith("1"):
            phone = phone[1:]
        if phone:
            sms_phones.add(phone)

    match_conditions = []
    if meta_user_ids:
        match_conditions.append(Lead.facebook_user_id.in_(meta_user_ids))
    if sms_phones:
        normalized_lead_phone = func.right(
            func.regexp_replace(Lead.phone, r"\D", "", "g"),
            10,
        )
        match_conditions.append(normalized_lead_phone.in_(sms_phones))

    leads = []
    if match_conditions:
        leads = (
            db.query(Lead)
            .options(joinedload(Lead.company), joinedload(Lead.assignee))
            .filter(Lead.company_id.in_(company_ids))
            .filter(or_(*match_conditions))
            .all()
        )

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
