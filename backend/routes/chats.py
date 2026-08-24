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
from db import calls_table, conversations_table, sms_messages_table
from libs.common.phone import normalize_digits
from libs.common.phone import phone_variants
from models import Company, Lead, User, UserCompany

logger = logging.getLogger("moving-crm")
router = APIRouter(prefix="/api/chats", tags=["Chats"])
DONE_CURSOR = {"__done": True}
SMS_TIMESTAMP_INDEX = "record-type-timestamp-index"
META_TIMESTAMP_INDEX = "record-type-timestamp-index"
CALLS_TIMESTAMP_INDEX = "record-type-timestamp-index"


def _user_company_ids(user: User, db: Session) -> list[str]:
    rows = db.query(UserCompany.company_id).filter(UserCompany.user_id == user.id).all()
    if rows:
        return [row[0] for row in rows]
    if user.role == "admin":
        return [row[0] for row in db.query(Company.id).all()]
    return []


def _query_meta_page(start_key: dict | None, limit: int) -> tuple[list[dict], dict | None]:
    kwargs: dict = {
        "IndexName": META_TIMESTAMP_INDEX,
        "KeyConditionExpression": Key("record_type").eq("message"),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    response = conversations_table.query(**kwargs)
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


def _phone(value) -> str:
    digits = normalize_digits(str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


@router.get("/calls")
def get_latest_calls(
    cursor: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view all calls")
    company_ids = _user_company_ids(user, db)
    if not company_ids:
        return {"items": [], "next_cursor": "", "has_more": False}
    start_key, _ = _decode_cursor(cursor)
    kwargs: dict = {
        "IndexName": CALLS_TIMESTAMP_INDEX,
        "KeyConditionExpression": Key("record_type").eq("call"),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    try:
        response = calls_table.query(**kwargs)
    except ClientError as exc:
        logger.error("Could not load calls: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch calls") from exc
    records = response.get("Items", [])
    next_key = response.get("LastEvaluatedKey")

    client_phones = {_phone(item.get("phone_number")) for item in records if _phone(item.get("phone_number"))}
    normalized_lead_phone = func.right(func.regexp_replace(Lead.phone, r"\D", "", "g"), 10)
    leads = (
        db.query(Lead)
        .options(joinedload(Lead.company), joinedload(Lead.assignee))
        .filter(Lead.company_id.in_(company_ids), normalized_lead_phone.in_(client_phones))
        .all()
        if client_phones else []
    )
    leads_by_phone: dict[str, list[Lead]] = {}
    for lead in leads:
        leads_by_phone.setdefault(_phone(lead.phone), []).append(lead)

    items = []
    for record in records:
        client_phone = _phone(record.get("phone_number"))
        company_phone = _phone(record.get("company_number"))
        matches = []
        for lead in leads_by_phone.get(client_phone, []):
            lead_company_phone = _phone(lead.company.phone) if lead.company else ""
            lead_rep_phone = _phone(lead.assignee.phone) if lead.assignee else ""
            if company_phone and company_phone in {lead_company_phone, lead_rep_phone}:
                matches.append(lead)
        lead = matches[0] if len(matches) == 1 else None
        direction = str(record.get("direction") or "").strip().lower()
        items.append({
            "call_id": str(record.get("message_id") or ""),
            "conversation_id": f"{client_phone}:{company_phone}",
            "lead_id": lead.id if lead else "",
            "client": lead.full_name if lead else str(record.get("phone_number") or client_phone),
            "client_identifier": client_phone,
            "company_identifier": company_phone,
            "company": lead.company.name if lead and lead.company else str(record.get("company_name") or company_phone),
            "rep": lead.assignee.name if lead and lead.assignee else "Unassigned",
            "direction": "inbound" if direction == "inbound" else "outbound",
            "answered": bool(record.get("answered")),
            "reason": str(record.get("reason") or ""),
            "timestamp": _timestamp(record.get("timestamp")),
        })
    return {
        "items": items,
        "next_cursor": _encode_cursor(next_key, None) if next_key else "",
        "has_more": bool(next_key),
    }


@router.get("/calls/history")
def get_call_history(
    phone: str = Query(...),
    company_number: str = Query(...),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view call history")
    expected_company = _phone(company_number)
    items: list[dict] = []
    seen: set[str] = set()
    try:
        for variant in phone_variants(phone):
            response = calls_table.query(KeyConditionExpression=Key("phone_number").eq(variant), ScanIndexForward=True)
            while True:
                for record in response.get("Items", []):
                    call_id = str(record.get("message_id") or "")
                    if call_id and call_id not in seen and _phone(record.get("company_number")) == expected_company:
                        seen.add(call_id)
                        items.append(record)
                if "LastEvaluatedKey" not in response:
                    break
                response = calls_table.query(KeyConditionExpression=Key("phone_number").eq(variant), ScanIndexForward=True, ExclusiveStartKey=response["LastEvaluatedKey"])
    except ClientError as exc:
        logger.error("Could not load call history: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch call history") from exc
    items.sort(key=lambda item: _timestamp(item.get("timestamp")))
    return {"calls": items}


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
                page, meta_next = _query_meta_page(meta_next, meta_limit)
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
                        number_id = str(message.get("number_id") or "").strip()
                        conversation_keys.add(("sms", phone, number_id))
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
    sms_number_ids: set[str] = set()
    for message in sms_messages:
        phone = normalize_digits(str(message.get("phone_number") or ""))
        if len(phone) == 11 and phone.startswith("1"):
            phone = phone[1:]
        if phone:
            sms_phones.add(phone)
        number_id = str(message.get("number_id") or "").strip()
        if number_id:
            sms_number_ids.add(number_id)

    number_rep_names: dict[str, str] = {}
    number_company_names: dict[str, str] = {}
    page_company_names: dict[str, str] = {}
    company_rows = db.query(Company).filter(Company.id.in_(company_ids)).all()
    for company in company_rows:
        company_name = str(getattr(company, "name", "") or "").strip()
        number_id = str(getattr(company, "aircall_number_id", "") or "").strip()
        page_id = str(getattr(company, "facebook_page_id", "") or "").strip()
        if number_id:
            number_company_names[number_id] = company_name
        if page_id:
            page_company_names[page_id] = company_name
    if sms_number_ids:
        rep_rows = db.query(User).filter(User.aircall_number_id.in_(sms_number_ids)).all()
        number_rep_names = {
            str(getattr(rep, "aircall_number_id", "") or "").strip(): str(getattr(rep, "name", "") or "").strip()
            for rep in rep_rows
            if getattr(rep, "aircall_number_id", None)
        }

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
            sms_phone_leads.setdefault(phone, []).append(lead)

    latest: dict[tuple[str, str], dict] = {}

    def add_message(lead: Lead, platform: str, message: dict, rep_name: str | None = None) -> None:
        timestamp = _timestamp(message.get("timestamp"))
        key = (lead.id, platform)
        if key in latest and latest[key]["timestamp"] >= timestamp:
            return
        latest[key] = {
            "conversation_id": f"lead:{lead.id}:{platform}",
            "lead_id": lead.id,
            "client": lead.full_name or lead.phone or "Unknown client",
            "rep": rep_name if rep_name is not None else (lead.assignee.name if lead.assignee else ""),
            "company": lead.company.name if lead.company else "",
            "platform": platform,
            "message": str(message.get("text") or ""),
            "timestamp": timestamp,
            "direction": str(message.get("direction") or message.get("role") or ""),
            "message_partition_key": str(message.get("phone_number") or message.get("user_id") or ""),
            "company_identifier": str(message.get("number_id") or message.get("page_id") or ""),
            "message_timestamp": message.get("timestamp"),
            "conversation_ended": bool(message.get("conversation_ended", False)),
        }

    for message in meta_messages:
        platform = str(message.get("platform") or "").strip().lower()
        if platform not in {"messenger", "instagram"}:
            continue
        lead = meta_leads.get(str(message.get("user_id") or ""))
        if lead:
            add_message(lead, platform, message)
        else:
            user_id = str(message.get("user_id") or "").strip()
            if not user_id:
                continue
            timestamp = _timestamp(message.get("timestamp"))
            key = (f"unmatched:{platform}:{user_id}", platform)
            if key not in latest or latest[key]["timestamp"] < timestamp:
                latest[key] = {
                    "conversation_id": f"unmatched:{platform}:{user_id}",
                    "lead_id": "",
                    "client": user_id,
                    "rep": "",
                    "company": page_company_names.get(str(message.get("page_id") or ""), ""),
                    "platform": platform,
                    "message": str(message.get("text") or ""),
                    "timestamp": timestamp,
                    "direction": str(message.get("role") or ""),
                    "message_partition_key": user_id,
                    "company_identifier": str(message.get("page_id") or ""),
                    "message_timestamp": message.get("timestamp"),
                    "conversation_ended": bool(message.get("conversation_ended", False)),
                }

    for message in sms_messages:
        phone = normalize_digits(str(message.get("phone_number") or ""))
        if len(phone) == 11 and phone.startswith("1"):
            phone = phone[1:]
        number_id = str(message.get("number_id") or "").strip()
        exact_matches: list[Lead] = []
        if number_id:
            for candidate in sms_phone_leads.get(phone, []):
                rep_number_id = (
                    str(getattr(candidate.assignee, "aircall_number_id", "") or "").strip()
                    if candidate.assignee else ""
                )
                company_number_id = (
                    str(getattr(candidate.company, "aircall_number_id", "") or "").strip()
                    if candidate.company else ""
                )
                if number_id in {rep_number_id, company_number_id}:
                    exact_matches.append(candidate)
        lead = max(exact_matches, key=_lead_time) if exact_matches else None
        if lead:
            # The exact number_id match selected the lead. Rep identity comes
            # from that matched CRM relationship, never from DynamoDB name fields.
            add_message(lead, "sms", message)
        else:
            timestamp = _timestamp(message.get("timestamp"))
            key = (f"unmatched:{phone}:{number_id}", "sms")
            if key not in latest or latest[key]["timestamp"] < timestamp:
                latest[key] = {
                    "conversation_id": f"unmatched:{phone}:{number_id}",
                    "lead_id": "",
                    "client": str(message.get("phone_number") or phone or "Unknown client"),
                    "rep": number_rep_names.get(number_id, ""),
                    "company": number_company_names.get(number_id) or str(message.get("company_name") or ""),
                    "platform": "sms",
                    "message": str(message.get("text") or ""),
                    "timestamp": timestamp,
                    "direction": str(message.get("direction") or ""),
                    "message_partition_key": str(message.get("phone_number") or ""),
                    "company_identifier": number_id,
                    "message_timestamp": message.get("timestamp"),
                    "conversation_ended": bool(message.get("conversation_ended", False)),
                }

    has_more = not meta_done or not sms_done
    return {
        "items": sorted(latest.values(), key=lambda item: item["timestamp"], reverse=True),
        "next_cursor": _encode_cursor(
            meta_next if not meta_done else DONE_CURSOR,
            sms_next if not sms_done else DONE_CURSOR,
        ) if has_more else "",
        "has_more": has_more,
    }
