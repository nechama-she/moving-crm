"""Consume source-message DynamoDB streams into the CRM-owned message_states table."""

import json
import logging
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.types import TypeDeserializer
from sqlalchemy import delete, func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import joinedload

from database import SessionLocal
from models import AppSetting, Company, Lead, MessageState, MissedCallState, User
from communication_associations import find_association
from meta_attachment_archiver import archive_meta_attachments
from realtime import publish_realtime_event


logger = logging.getLogger("moving-crm.message-stream")
logger.setLevel(logging.INFO)
_deserialize = TypeDeserializer().deserialize
IGNORED_CALL_NUMBERS_SETTING = "sales_work_queue.ignored_call_numbers"


def _image(record: dict) -> dict:
    raw = ((record.get("dynamodb") or {}).get("NewImage") or {})
    return {key: _deserialize(value) for key, value in raw.items()}


def _digits(value) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _ignored_call_numbers(db) -> set[str]:
    row = db.query(AppSetting).filter(AppSetting.key == IGNORED_CALL_NUMBERS_SETTING).first()
    if not row or not row.value:
        return set()
    try:
        values = json.loads(row.value)
    except (TypeError, ValueError):
        logger.warning("Invalid ignored call numbers setting")
        return set()
    return {_digits(value) for value in values if _digits(value)}


def _occurred_at(value) -> datetime:
    numeric = float(value)
    if numeric > 10_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, tz=timezone.utc)


def _channel(record: dict, item: dict) -> str:
    arn = str(record.get("eventSourceARN") or "")
    if ":table/sms_messages/stream/" in arn:
        return "sms"
    if ":table/conversations/stream/" not in arn:
        raise ValueError(f"Unsupported DynamoDB stream ARN: {arn}")
    platform = str(item.get("platform") or "messenger").strip().lower()
    return platform if platform in {"messenger", "instagram"} else "messenger"


def _direction(channel: str, item: dict) -> str:
    if channel == "sms":
        value = str(item.get("direction") or "").strip().lower()
        sender = str(item.get("sales_name") or "").strip().lower()
        if value == "draft" or sender in {"ai", "assistant", "bot"}:
            return "ignored"
        if value in {"received", "inbound"}:
            return "inbound"
        if value in {"sent", "outbound"}:
            return "outbound"
    role = str(item.get("role") or "").strip().lower()
    if role in {"ai", "assistant", "bot"}:
        return "ignored"
    return "inbound" if role in {"user", "client", "customer"} else "outbound"


def _conversation_identifiers(channel: str, item: dict) -> tuple[str, str]:
    if channel == "sms":
        return _digits(item.get("phone_number")), _digits(item.get("company_number"))
    return str(item.get("user_id") or "").strip(), str(item.get("page_id") or "").strip()


def _log_sql(db, operation: str, statement) -> None:
    compiled = statement.compile(dialect=db.bind.dialect, compile_kwargs={"literal_binds": False})
    logger.info("message_states SQL operation=%s statement=%s params=%s", operation, compiled, compiled.params)


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


def _display_row(db, inserted: dict, item: dict) -> dict:
    lead = None
    if inserted.get("lead_id"):
        lead = (
            db.query(Lead)
            .options(joinedload(Lead.company), joinedload(Lead.assignee))
            .filter(Lead.id == inserted["lead_id"])
            .first()
        )
    company = lead.company.name if lead and lead.company else ""
    destination_number = _digits(inserted["company_identifier"]) if inserted["channel"] == "sms" else ""
    destination_name = ""
    if destination_number:
        rep = next((name for name, phone in db.query(User.name, User.phone).all() if _digits(phone) == destination_number), "")
        destination_company = next((name for name, phone in db.query(Company.name, Company.phone).all() if _digits(phone) == destination_number), "")
        destination_name = rep or destination_company or "Unknown number"
    return {
        "channel": inserted["channel"],
        "message_id": inserted["message_id"],
        "lead_id": inserted.get("lead_id") or "",
        "client_identifier": inserted["client_identifier"],
        "client": lead.full_name if lead else inserted["client_identifier"],
        "client_number": _digits(inserted["client_identifier"]) if inserted["channel"] == "sms" else "",
        "message": str(item.get("text") or ""),
        "attachments": item.get("attachments") or [],
        "rep": lead.assignee.name if lead and lead.assignee else "Unassigned",
        "company": company,
        "destination_number": destination_number,
        "destination_name": destination_name,
        "occurred_at": inserted["occurred_at"].isoformat(),
    }


def _call_display_row(db, inserted: dict) -> dict:
    lead = None
    if inserted.get("lead_id"):
        lead = (
            db.query(Lead)
            .options(joinedload(Lead.company), joinedload(Lead.assignee))
            .filter(Lead.id == inserted["lead_id"])
            .first()
        )
    ring_number = _digits(inserted["company_identifier"])
    rep = next(
        (name for name, phone in db.query(User.name, User.phone).all() if _digits(phone) == ring_number),
        "",
    )
    company = next(
        (name for name, phone in db.query(Company.name, Company.phone).all() if _digits(phone) == ring_number),
        "",
    )
    ring_target = rep or company or "Unknown number"
    return {
        "call_id": inserted["call_id"],
        "lead_id": inserted.get("lead_id") or "",
        "client_identifier": inserted["client_identifier"],
        "company_identifier": inserted["company_identifier"],
        "client": lead.full_name if lead else inserted["client_identifier"],
        "rep": lead.assignee.name if lead and lead.assignee else "Unassigned",
        "company": lead.company.name if lead and lead.company else "",
        "ring_number": ring_number,
        "ring_target": ring_target,
        "missed_count": inserted["missed_count"],
        "first_missed_at": inserted["first_missed_at"].isoformat(),
        "latest_missed_at": inserted["latest_missed_at"].isoformat(),
    }


def _process_call_record(db, record: dict, item: dict, event_id: str) -> tuple[bool, dict | None]:
    call_id = str(item.get("message_id") or "").strip()
    timestamp = item.get("timestamp")
    client_identifier = _digits(item.get("phone_number"))
    company_identifier = _digits(item.get("company_number"))
    if not call_id or timestamp is None or not client_identifier or not company_identifier:
        logger.warning("Skipping call without complete identifiers")
        return False, None

    ignored_numbers = _ignored_call_numbers(db)
    if client_identifier in ignored_numbers or company_identifier in ignored_numbers:
        logger.info("Ignoring call with configured number client=%s destination=%s", client_identifier, company_identifier)
        return True, None

    is_missed_inbound = (
        str(item.get("direction") or "").strip().lower() == "inbound"
        and item.get("answered") is False
    )
    state_filter = (
        MissedCallState.client_identifier == client_identifier,
        MissedCallState.company_identifier == company_identifier,
    )
    if not is_missed_inbound:
        clear_statement = delete(MissedCallState).where(*state_filter).returning(MissedCallState.call_id)
        _log_sql(db, "clear_missed_calls", clear_statement)
        removed_ids = [row[0] for row in db.execute(clear_statement).all()]
        if not removed_ids:
            return True, {
                "type": "call_activity_changed",
                "event_id": f"stream:{event_id}",
                "action": "recorded",
            }
        return True, {
            "type": "missed_call_state_changed",
            "event_id": f"stream:{event_id}",
            "action": "remove",
            "call_ids": removed_ids,
            "count_delta": -1,
        }

    lead_id = _valid_explicit_lead_id(db, item.get("lead_id"))
    if not lead_id:
        association = find_association(db, "phone", client_identifier, company_identifier)
        lead_id = association.lead_id if association else None
    if not lead_id:
        lead_id = _resolve_sms_lead_id(db, item)
    occurred_at = _occurred_at(timestamp)
    statement = insert(MissedCallState).values(
        client_identifier=client_identifier,
        company_identifier=company_identifier,
        call_id=call_id,
        lead_id=lead_id,
        missed_count=1,
        first_missed_at=occurred_at,
        latest_missed_at=occurred_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[MissedCallState.client_identifier, MissedCallState.company_identifier],
        set_={
            "call_id": statement.excluded.call_id,
            "lead_id": func.coalesce(statement.excluded.lead_id, MissedCallState.lead_id),
            "missed_count": MissedCallState.missed_count + 1,
            "latest_missed_at": statement.excluded.latest_missed_at,
        },
    ).returning(
        MissedCallState.client_identifier,
        MissedCallState.company_identifier,
        MissedCallState.call_id,
        MissedCallState.lead_id,
        MissedCallState.missed_count,
        MissedCallState.first_missed_at,
        MissedCallState.latest_missed_at,
    )
    _log_sql(db, "upsert_missed_call", statement)
    inserted = dict(db.execute(statement).mappings().one())
    return True, {
        "type": "missed_call_state_changed",
        "event_id": f"stream:{event_id}",
        "action": "upsert",
        "row": _call_display_row(db, inserted),
        "count_delta": 1 if inserted["missed_count"] == 1 else 0,
    }


def _process_record(db, record: dict, event_id: str) -> tuple[bool, dict | None]:
    if record.get("eventName") != "INSERT":
        return False, None
    item = _image(record)
    arn = str(record.get("eventSourceARN") or "")
    if ":table/calls/stream/" in arn:
        if str(item.get("record_type") or "call").lower() != "call":
            return False, None
        return _process_call_record(db, record, item, event_id)
    if str(item.get("record_type") or "message").lower() != "message":
        return False, None

    message_id = str(item.get("message_id") or "").strip()
    timestamp = item.get("timestamp")
    if not message_id or timestamp is None:
        logger.warning("Skipping source record without message_id/timestamp")
        return False, None

    channel = _channel(record, item)
    direction = _direction(channel, item)
    if direction == "ignored":
        logger.info("Ignoring automated %s message role=%s", channel, item.get("role"))
        return True, None
    client_identifier, company_identifier = _conversation_identifiers(channel, item)
    if not client_identifier or not company_identifier:
        logger.warning("Skipping %s message without complete conversation identifiers", channel)
        return False, None

    if channel == "sms" and ({client_identifier, company_identifier} & _ignored_call_numbers(db)):
        logger.info("Ignoring SMS with configured number client=%s destination=%s", client_identifier, company_identifier)
        return True, None

    lead_id = _valid_explicit_lead_id(db, item.get("lead_id"))
    if not lead_id:
        association = find_association(db, channel, client_identifier, company_identifier)
        lead_id = association.lead_id if association else None
    if not lead_id:
        lead_id = _resolve_sms_lead_id(db, item) if channel == "sms" else _resolve_meta_lead_id(db, item)

    if channel in {"messenger", "instagram"} and item.get("attachments"):
        archived = archive_meta_attachments(
            db,
            lead_id=lead_id,
            channel=channel,
            message_id=message_id,
            attachments=item.get("attachments"),
            occurred_at=_occurred_at(timestamp),
        )
        if archived:
            logger.info("Archived %d %s attachments for lead %s message %s", archived, channel, lead_id, message_id)

    conversation_filter = (
        MessageState.channel == channel,
        MessageState.client_identifier == client_identifier,
        MessageState.company_identifier == company_identifier,
    )

    # An outbound reply resolves the current unanswered inbound message. Outbound
    # messages are events, not durable state rows. Manually ended rows remain.
    if direction == "outbound":
        clear_statement = delete(MessageState).where(
            *conversation_filter,
            MessageState.conversation_ended.is_(False),
        ).returning(MessageState.message_id)
        _log_sql(db, "clear_answered", clear_statement)
        clear_result = db.execute(clear_statement)
        removed_ids = [row[0] for row in clear_result.all()]
        logger.info(
            "message_states SQL response operation=clear_answered rowcount=%s channel=%s client_identifier=%s company_identifier=%s",
            len(removed_ids),
            channel,
            client_identifier,
            company_identifier,
        )
        event = None
        if removed_ids:
            event = {
                "type": "message_state_changed",
                "event_id": f"stream:{event_id}",
                "action": "remove",
                "channel": channel,
                "message_ids": removed_ids,
                "count_delta": {"unanswered": -len(removed_ids), "ended": 0},
            }
        else:
            event = {
                "type": "message_activity_changed",
                "event_id": f"stream:{event_id}",
                "action": "recorded",
                "channel": channel,
            }
        return True, event

    # A new inbound message reopens an ended conversation and replaces any older
    # unanswered inbound, keeping exactly one current row per conversation.
    replace_statement = delete(MessageState).where(*conversation_filter).returning(
        MessageState.message_id, MessageState.conversation_ended
    )
    _log_sql(db, "remove_previous_state", replace_statement)
    replace_result = db.execute(replace_statement)
    replaced = [dict(row._mapping) for row in replace_result.all()]
    logger.info(
        "message_states SQL response operation=remove_previous_state rowcount=%s channel=%s client_identifier=%s company_identifier=%s",
        len(replaced),
        channel,
        client_identifier,
        company_identifier,
    )
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
    ).returning(
        MessageState.channel,
        MessageState.message_id,
        MessageState.lead_id,
        MessageState.client_identifier,
        MessageState.company_identifier,
        MessageState.direction,
        MessageState.conversation_ended,
        MessageState.occurred_at,
    )
    _log_sql(db, "upsert_inbound", statement)
    inserted = dict(db.execute(statement).mappings().one())
    logger.info("message_states SQL response operation=upsert_inbound row=%s", inserted)
    prior_unanswered = sum(not row["conversation_ended"] for row in replaced)
    prior_ended = len(replaced) - prior_unanswered
    return True, {
        "type": "message_state_changed",
        "event_id": f"stream:{event_id}",
        "action": "upsert",
        "row": _display_row(db, inserted, item),
        "removed_message_ids": [row["message_id"] for row in replaced],
        "count_delta": {"unanswered": 1 - prior_unanswered, "ended": -prior_ended},
    }


def handler(event, context):
    db = SessionLocal()
    processed = 0
    failures = []
    realtime_events = []
    try:
        for record in event.get("Records") or []:
            event_id = str(((record.get("dynamodb") or {}).get("SequenceNumber")) or "")
            try:
                was_processed, realtime_event = _process_record(db, record, event_id)
                if was_processed:
                    db.commit()
                    processed += 1
                    if realtime_event:
                        realtime_events.append(realtime_event)
            except Exception:
                db.rollback()
                logger.exception("Failed message stream record %s", event_id)
                failures.append({"itemIdentifier": event_id})
        if realtime_events:
            publish_realtime_event({"type": "sales_work_queue_batch", "events": realtime_events})
        logger.info("Processed %d message state records; failures=%d realtime_events=%d", processed, len(failures), len(realtime_events))
        return {"batchItemFailures": failures}
    finally:
        db.close()
