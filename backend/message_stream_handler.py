"""Consume source-message DynamoDB streams into the CRM-owned message_states table."""

import logging
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeDeserializer
from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert

from database import SessionLocal
from models import Company, Lead, MessageState, User


logger = logging.getLogger("moving-crm.message-stream")
logger.setLevel(logging.INFO)
_deserialize = TypeDeserializer().deserialize


def _image(record: dict) -> dict:
    raw = ((record.get("dynamodb") or {}).get("NewImage") or {})
    return {key: _deserialize(value) for key, value in raw.items()}


def _digits(value) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _occurred_at(value) -> datetime:
    numeric = float(value)
    if numeric > 10_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, tz=timezone.utc)


def _channel(record: dict, item: dict) -> str:
    arn = str(record.get("eventSourceARN") or "")
    if "/table/sms_messages/" in arn:
        return "sms"
    platform = str(item.get("platform") or "messenger").strip().lower()
    return platform if platform in {"messenger", "instagram"} else "messenger"


def _direction(channel: str, item: dict) -> str:
    if channel == "sms":
        value = str(item.get("direction") or "").strip().lower()
        if value in {"received", "inbound"}:
            return "inbound"
        if value in {"sent", "outbound"}:
            return "outbound"
    role = str(item.get("role") or "").strip().lower()
    return "inbound" if role in {"user", "client", "customer"} else "outbound"


def _conversation_identifiers(channel: str, item: dict) -> tuple[str, str]:
    if channel == "sms":
        return _digits(item.get("phone_number")), _digits(item.get("company_number"))
    return str(item.get("user_id") or "").strip(), str(item.get("page_id") or "").strip()


def _valid_explicit_lead_id(db, value) -> str | None:
    lead_id = str(value or "").strip()
    if not lead_id:
        return None
    return lead_id if db.query(Lead.id).filter(Lead.id == lead_id).first() else None


def _resolve_sms_lead_id(db, item: dict) -> str | None:
    client_phone = _digits(item.get("phone_number"))
    destination_phone = _digits(item.get("company_number"))
    if not client_phone or not destination_phone:
        return None

    normalized_lead_phone = func.right(func.regexp_replace(Lead.phone, r"\D", "", "g"), 10)
    normalized_company_phone = func.right(func.regexp_replace(Company.phone, r"\D", "", "g"), 10)
    normalized_rep_phone = func.right(func.regexp_replace(User.phone, r"\D", "", "g"), 10)
    rows = (
        db.query(Lead.id)
        .join(Company, Company.id == Lead.company_id)
        .outerjoin(User, User.id == Lead.assigned_to)
        .filter(
            normalized_lead_phone == client_phone,
            or_(normalized_company_phone == destination_phone, normalized_rep_phone == destination_phone),
        )
        .limit(2)
        .all()
    )
    return rows[0][0] if len(rows) == 1 else None


def _resolve_meta_lead_id(db, item: dict) -> str | None:
    user_id = str(item.get("user_id") or "").strip()
    page_id = str(item.get("page_id") or "").strip()
    if not user_id or not page_id:
        return None
    rows = (
        db.query(Lead.id)
        .join(Company, Company.id == Lead.company_id)
        .filter(Lead.facebook_user_id == user_id, Company.facebook_page_id == page_id)
        .limit(2)
        .all()
    )
    return rows[0][0] if len(rows) == 1 else None


def _process_record(db, record: dict) -> bool:
    if record.get("eventName") != "INSERT":
        return False
    item = _image(record)
    if str(item.get("record_type") or "message").lower() != "message":
        return False

    message_id = str(item.get("message_id") or "").strip()
    timestamp = item.get("timestamp")
    if not message_id or timestamp is None:
        logger.warning("Skipping source record without message_id/timestamp")
        return False

    channel = _channel(record, item)
    direction = _direction(channel, item)
    client_identifier, company_identifier = _conversation_identifiers(channel, item)
    if not client_identifier or not company_identifier:
        logger.warning("Skipping %s message without complete conversation identifiers", channel)
        return False

    conversation_filter = (
        MessageState.channel == channel,
        MessageState.client_identifier == client_identifier,
        MessageState.company_identifier == company_identifier,
    )

    # An outbound reply resolves the current unanswered inbound message. Outbound
    # messages are events, not durable state rows. Manually ended rows remain.
    if direction == "outbound":
        db.query(MessageState).filter(
            *conversation_filter,
            MessageState.conversation_ended.is_(False),
        ).delete(synchronize_session=False)
        return True

    lead_id = _valid_explicit_lead_id(db, item.get("lead_id"))
    if not lead_id:
        lead_id = _resolve_sms_lead_id(db, item) if channel == "sms" else _resolve_meta_lead_id(db, item)

    # A new inbound message reopens an ended conversation and replaces any older
    # unanswered inbound, keeping exactly one current row per conversation.
    db.query(MessageState).filter(*conversation_filter).delete(synchronize_session=False)
    statement = insert(MessageState).values(
        channel=channel,
        message_id=message_id,
        lead_id=lead_id,
        client_identifier=client_identifier,
        company_identifier=company_identifier,
        direction=direction,
        conversation_ended=False,
        occurred_at=_occurred_at(timestamp),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[MessageState.channel, MessageState.message_id],
        set_={
            "lead_id": func.coalesce(statement.excluded.lead_id, MessageState.lead_id),
            "direction": statement.excluded.direction,
            "occurred_at": statement.excluded.occurred_at,
        },
    )
    db.execute(statement)
    return True


def handler(event, context):
    db = SessionLocal()
    processed = 0
    failures = []
    try:
        for record in event.get("Records") or []:
            event_id = str(((record.get("dynamodb") or {}).get("SequenceNumber")) or "")
            try:
                if _process_record(db, record):
                    db.commit()
                    processed += 1
            except Exception:
                db.rollback()
                logger.exception("Failed message stream record %s", event_id)
                failures.append({"itemIdentifier": event_id})
        logger.info("Processed %d message state records; failures=%d", processed, len(failures))
        return {"batchItemFailures": failures}
    finally:
        db.close()
