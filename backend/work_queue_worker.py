"""Event-driven, resumable ingestion and incremental lead projection."""
import json
import logging
import os
import time
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import joinedload, load_only

from models import Company, Lead, User
from work_queue_models import QueueActivity, QueueCheckpoint, QueueDirty, QueueLead
from work_queue_rules import _digits, _epoch, _smartmoving_created_at, calculate_followup_rows
from work_queue_store import SOURCES, FIELDS, checkpoint, dump, ingest_activity, ingestion_failed, insert_for, save_checkpoint, utc

logger = logging.getLogger("moving-crm.queue-worker")


def invoke_event(function, payload):
    result = boto3.client("lambda").invoke(FunctionName=function,
        InvocationType="Event", Payload=json.dumps(payload).encode())
    if result.get("StatusCode") != 202:
        raise RuntimeError("Queue event delivery was not accepted")


def schedule_deadline(db):
    """Replace the single next deadline; never create a recurring schedule."""
    due = db.query(func.min(QueueLead.next_due_at)).scalar()
    client = boto3.client("scheduler")
    previous = checkpoint(db, "deadline") or {}
    prefix = os.environ["WORK_QUEUE_DEADLINE_NAME"]
    def remove(name):
        try:
            client.delete_schedule(Name=name)
        except client.exceptions.ResourceNotFoundException:
            pass
    if due is None:
        if previous.get("name"):
            remove(previous["name"])
            save_checkpoint(db, "deadline", {})
            db.commit()
        return
    due = max(utc(due), datetime.now(timezone.utc) + timedelta(seconds=2))
    # Round the expression upward. AWS delivery can be up to a minute later.
    due = due.replace(microsecond=0) + timedelta(seconds=1)
    name = f"{prefix}-{int(due.timestamp())}"
    if previous.get("name") == name:
        return  # The same future deadline is already installed.
    args = dict(Name=name, ScheduleExpression=f"at({due.strftime('%Y-%m-%dT%H:%M:%S')})",
        ScheduleExpressionTimezone="UTC", FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE", Target={
            "Arn": os.environ["WORK_QUEUE_FUNCTION_ARN"],
            "RoleArn": os.environ["WORK_QUEUE_SCHEDULER_ROLE_ARN"],
            "Input": '{"source":"deadline"}',
        })
    try:
        client.create_schedule(**args)
    except client.exceptions.ConflictException:
        client.update_schedule(**args)
    if previous.get("name") and previous["name"] != name:
        remove(previous["name"])
    save_checkpoint(db, "deadline", {"name": name})
    db.commit()


def bootstrap_page(db, source, table):
    """Commit one bounded source page and its cursor together; safe to resume."""
    progress = checkpoint(db, "bootstrap:" + source) or {}
    if progress.get("done"):
        return True
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL moving_crm.queue_worker = 'on'"))
    names = {f"#f{i}": field for i, field in enumerate(FIELDS)}
    kwargs = dict(Limit=200, ConsistentRead=True, ProjectionExpression=", ".join(names), ExpressionAttributeNames=names)
    if progress.get("cursor"):
        kwargs["ExclusiveStartKey"] = {key: Decimal(value) if key == "timestamp" else value for key, value in progress["cursor"].items()}
    page = table.scan(**kwargs)
    expected = "call" if source == "calls" else "message"
    for item in page.get("Items", []):
        # Match the existing timestamp-index eligibility exactly.
        if item.get("record_type") == expected:
            ingest_activity(db, source, item, bootstrap=True)
    cursor = page.get("LastEvaluatedKey")
    save_checkpoint(db, "bootstrap:" + source, {"cursor": cursor, "done": not bool(cursor)})
    db.commit()
    return not bool(cursor)


def normalized_messages(activities):
    messages = []
    for activity in activities:
        if activity.source == "calls":
            continue
        item = json.loads(activity.payload)
        if activity.source == "sms_messages":
            sender = str(item.get("sales_name") or item.get("company_name") or "").strip().lower()
            if str(item.get("direction") or "").strip().lower() not in {"sent", "outbound"} or sender in {"ai", "assistant", "bot"}:
                continue
            messages.append(dict(channel="sms", occurred_at=utc(activity.occurred_at), client=activity.client,
                                 destination=_digits(item.get("company_number")), number_id=str(item.get("number_id") or "").strip()))
        else:
            if str(item.get("role") or "").strip().lower() in {"user", "client", "customer", "ai", "assistant", "bot"} or str(item.get("sales_name") or "").strip().lower() in {"ai", "assistant", "bot"}:
                continue
            messages.append(dict(channel=str(item.get("platform") or "messenger").strip().lower(),
                                 occurred_at=utc(activity.occurred_at), client=activity.client, page_id=str(item.get("page_id") or "").strip()))
    return sorted(messages, key=lambda item: item["occurred_at"])


def project_lead(db, lead, tracking_start, now):
    if (tracking_start is None or lead.priority != 0
            or str(lead.status or "").strip().lower() not in {"", "new", "contacted", "quoted"}
            or (lead.company and str(lead.company.name or "").strip().lower() == "mirit great american")):
        return None
    created_at = _smartmoving_created_at(lead.created_time) or utc(lead.created_at)
    if created_at < tracking_start:
        return None
    clients = {_digits(lead.phone), str(lead.facebook_user_id or "").strip()} - {""}
    activities = db.query(QueueActivity).filter(QueueActivity.client.in_(clients), QueueActivity.occurred_at >= created_at,
                                               QueueActivity.deleted.is_(False)).all() if clients else []
    calls = [json.loads(row.payload) for row in activities if row.source == "calls"]
    calls = [call for call in calls if str(call.get("direction") or "").strip().lower() == "outbound"]
    destinations = {_digits(lead.company.phone) if lead.company else "", _digits(lead.assignee.phone) if lead.assignee else ""} - {""}
    contacted = any(_digits(call.get("phone_number")) == _digits(lead.phone) and _digits(call.get("company_number")) in destinations for call in calls)
    first_category = ""
    # Preserve the current first-contact eligibility's CRM creation cutoff.
    if utc(lead.created_at) >= tracking_start and not contacted:
        first_category = "new" if created_at > now - timedelta(minutes=30) else "overdue"
    first = dict(lead_id=lead.id, client=lead.full_name or lead.phone or "Unknown client", client_phone=lead.phone or "",
                 rep=lead.assignee.name if lead.assignee else "", company=lead.company.name if lead.company else "",
                 status=lead.status or "new", created_at=created_at.isoformat(),
                 age_minutes=max(0, int((now - created_at).total_seconds() // 60)))
    followup = calculate_followup_rows([(lead, created_at)], calls, normalized_messages(activities), now)[0] if str(lead.phone or "").strip() else None
    deadlines = [created_at + timedelta(minutes=30)] if first_category == "new" else []
    if followup:
        for attempt in [*followup["attempts"], *followup["message_attempts"]]:
            if attempt["status"] in {"open", "upcoming"}:
                deadlines.extend(datetime.fromisoformat(attempt[key]).astimezone(timezone.utc) + timedelta(microseconds=1)
                                 for key in ("scheduled_start", "scheduled_end"))
    future = [value for value in deadlines if value > now]
    return dict(lead_id=lead.id, rep=first["rep"], company=first["company"], first_category=first_category,
                first_payload=dump(first), followup=followup is not None,
                overdue=bool(followup and (followup["overdue_count"] or followup["overdue_message_count"])),
                followup_payload=dump(followup or {}), created_at=created_at, crm_created_at=utc(lead.created_at),
                computed_at=now, next_due_at=min(future) if future else None)


def process_one(db, tracking_start, now):
    dirty = db.query(QueueDirty).order_by(QueueDirty.lead_id).with_for_update(skip_locked=True).first()
    if dirty is None:
        return False
    lead = db.query(Lead).options(
        load_only(Lead.id, Lead.full_name, Lead.phone, Lead.status, Lead.priority, Lead.created_at, Lead.created_time, Lead.facebook_user_id),
        joinedload(Lead.company).load_only(Company.name, Company.phone, Company.timezone, Company.aircall_number_id, Company.facebook_page_id),
        joinedload(Lead.assignee).load_only(User.name, User.phone, User.aircall_number_id),
    ).filter(Lead.id == dirty.lead_id).first()
    values = project_lead(db, lead, tracking_start, now) if lead else None
    if values is None:
        db.query(QueueLead).filter(QueueLead.lead_id == dirty.lead_id).delete()
    else:
        stmt = insert_for(db, QueueLead).values(**values)
        db.execute(stmt.on_conflict_do_update(index_elements=[QueueLead.lead_id], set_={key: getattr(stmt.excluded, key) for key in values if key != "lead_id"}))
    db.delete(dirty)
    db.commit()
    return True


def run(db, tables, *, seconds=45):
    deadline = time.monotonic() + seconds
    # Initial history ingestion is checkpointed, not performed by migration or HTTP.
    for source in SOURCES:
        while time.monotonic() < deadline:
            if bootstrap_page(db, source, tables[source]):
                break
        if not (checkpoint(db, "bootstrap:" + source) or {}).get("done"):
            return {"initializing": source}
    earliest = db.query(func.min(QueueActivity.occurred_at)).filter(QueueActivity.source == "calls", QueueActivity.deleted.is_(False)).scalar()
    tracking_start = utc(earliest) if earliest else None
    tracking_value = tracking_start.isoformat() if tracking_start else None
    # Any changed tracking cutoff invalidates all eligibility; normal runs only
    # touch changed leads and deadlines. Reconciliation also covers stale rows.
    previous = checkpoint(db, "tracking")
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL moving_crm.queue_worker = 'on'"))
    if previous is None or previous.get("start") != tracking_value:
        ids = select(Lead.id).union(select(QueueLead.lead_id)).subquery()
        db.execute(insert_for(db, QueueDirty).from_select(["lead_id"],
            select(ids.c.id).where(text("true")).order_by(ids.c.id)).on_conflict_do_nothing())
        save_checkpoint(db, "tracking", {"start": tracking_value})
    now = datetime.now(timezone.utc)
    db.execute(insert_for(db, QueueDirty).from_select(["lead_id"],
        select(QueueLead.lead_id).where(QueueLead.next_due_at <= now)
        .order_by(QueueLead.lead_id)).on_conflict_do_nothing())
    if db.query(QueueDirty.lead_id).first() is not None:
        # Persist before processing: a timeout after the final row commit must
        # not lose the completion notification when the retry finds no work.
        save_checkpoint(db, "projection_pending", {"updated_at": now.isoformat()})
    db.commit()
    count = 0
    while time.monotonic() < deadline and process_one(db, tracking_start, now):
        count += 1
    pending = db.query(QueueDirty.lead_id).first() is not None
    # Do not label a partial first build as ready or an unfinished batch as fresh.
    if not pending and not ingestion_failed(db) and (checkpoint(db, "projection_pending") or not checkpoint(db, "published")):
        save_checkpoint(db, "published", {"updated_at": datetime.now(timezone.utc).isoformat()})
        db.query(QueueCheckpoint).filter(QueueCheckpoint.key == "projection_pending").delete()
        db.commit()
    return {"processed": count, "pending": pending}


def handler(event, context):
    from database import SessionLocal
    from db import calls_table, sms_messages_table, conversations_table
    # Hold the advisory lock on a dedicated connection across per-lead commits.
    # It also protects against accidental duplicate scheduled/manual invocations.
    from database import engine
    lock_engine = create_engine(engine.url.set(host=os.environ.get("WORK_QUEUE_LOCK_HOST") or engine.url.host), poolclass=NullPool)
    with lock_engine.connect() as lock:
        if not lock.execute(text("SELECT pg_try_advisory_lock(78201401)")).scalar():
            # Do not acknowledge and lose a wake-up arriving at the end of a run.
            raise RuntimeError("Queue worker is busy; retry this event")
        lock.commit()
        try:
            with SessionLocal() as db:
                remaining = context.get_remaining_time_in_millis() / 1000 if context else 55
                result = run(db, {"calls": calls_table, "sms_messages": sms_messages_table, "conversations": conversations_table}, seconds=max(1, remaining - 10))
                if result.get("initializing") or result.get("pending"):
                    if event.get("source") != "listener":
                        invoke_event(os.environ["WORK_QUEUE_FUNCTION_NAME"], {"source": "continuation"})
                else:
                    schedule_deadline(db)
                    # Deliver only after all saved rows and counts have committed.
                    # Failure raises so Lambda retries instead of losing the update.
                    published = checkpoint(db, "published")
                    if published and checkpoint(db, "broadcast") != published:
                        invoke_event(os.environ["REALTIME_FUNCTION_NAME"], {
                            "action": "broadcast", "payload": {"type": "work_queue_updated"}})
                        save_checkpoint(db, "broadcast", published)
                        db.commit()
                logger.info("Queue worker result: %s", result)
                return result
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(78201401)"))
            lock.commit()
