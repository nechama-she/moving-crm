"""Activity ingestion and SQL-only queue reads; no AWS calls on read paths."""
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models import Lead
from work_queue_models import QueueActivity, QueueCheckpoint, QueueDirty, QueueLead
from work_queue_rules import _digits, _epoch

SOURCES = ("calls", "sms_messages", "conversations")
FIELDS = ("record_type", "message_id", "timestamp", "phone_number", "company_number",
          "user_id", "page_id", "platform", "direction", "role", "sales_name",
          "company_name", "number_id", "text", "attachments")


def insert_for(db, model):
    if db.bind.dialect.name == "sqlite":
        # SQLite is test-only and intentionally omitted from Lambda packages.
        from sqlalchemy.dialects.sqlite import insert
        return insert(model)
    return pg_insert(model)


def dump(value):
    return json.dumps(value, default=str, separators=(",", ":"))


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def checkpoint(db, key):
    row = db.get(QueueCheckpoint, key)
    return json.loads(row.value) if row else None


def save_checkpoint(db, key, value):
    stmt = insert_for(db, QueueCheckpoint).values(key=key, value=dump(value), updated_at=datetime.now(timezone.utc))
    db.execute(stmt.on_conflict_do_update(index_elements=[QueueCheckpoint.key],
                                        set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at}))


def mark_clients(db, clients):
    clients = {client for client in clients if client}
    if not clients:
        return
    # The production expression has a matching index installed by migration.
    phone = func.right(func.regexp_replace(Lead.phone, r"\D", "", "g"), 10)
    if db.bind.dialect.name == "sqlite":
        ids = [lead.id for lead in db.query(Lead).all() if _digits(lead.phone) in clients or lead.facebook_user_id in clients]
    else:
        ids = [row[0] for row in db.query(Lead.id).filter(or_(phone.in_(clients), Lead.facebook_user_id.in_(clients))).all()]
    if ids:
        db.execute(insert_for(db, QueueDirty).values([{"lead_id": value} for value in sorted(ids)])
                   .on_conflict_do_update(index_elements=[QueueDirty.lead_id], set_={"revision": QueueDirty.revision + 1}))


def ingest_activity(db, source, item, *, sequence=0, event_time=0, deleted=False, bootstrap=False):
    """Backfill cannot overwrite stream updates or tombstones. Replays are no-ops."""
    partition = "user_id" if source == "conversations" else "phone_number"
    if source not in SOURCES or item.get(partition) is None or item.get("timestamp") is None:
        raise ValueError("Queue activity is missing its source key")
    identity = dump([str(item[partition]), str(Decimal(str(item["timestamp"])).normalize())])
    source_key = hashlib.sha256(identity.encode()).hexdigest()
    existing = db.get(QueueActivity, (source, source_key))
    old_client = existing.client if existing else ""
    client = str(item[partition]).strip() if source == "conversations" else _digits(item[partition])
    values = dict(source=source, source_key=source_key, client=client,
                  message_id=str(item.get("message_id") or ""),
                  occurred_at=datetime.fromtimestamp(_epoch(item["timestamp"]), tz=timezone.utc),
                  event_time=Decimal(str(event_time)), sequence=Decimal(str(sequence)), deleted=deleted,
                  payload=dump({key: item[key] for key in FIELDS if key in item}))
    stmt = insert_for(db, QueueActivity).values(**values)
    if bootstrap:
        stmt = stmt.on_conflict_do_nothing(index_elements=[QueueActivity.source, QueueActivity.source_key])
    else:
        newer = or_(QueueActivity.event_time < stmt.excluded.event_time,
                    and_(QueueActivity.event_time == stmt.excluded.event_time, QueueActivity.sequence < stmt.excluded.sequence))
        stmt = stmt.on_conflict_do_update(index_elements=[QueueActivity.source, QueueActivity.source_key],
                                         set_={key: getattr(stmt.excluded, key) for key in values if key not in {"source", "source_key"}},
                                         where=newer)
    changed = db.execute(stmt).rowcount
    if changed and not bootstrap:
        mark_clients(db, {client, old_client})
    return bool(changed)


def ingestion_failed(db):
    return db.query(QueueCheckpoint.key).filter(QueueCheckpoint.key.startswith("ingestion_error")).first() is not None


def status(db):
    state = checkpoint(db, "published")
    updated = datetime.fromisoformat(state["updated_at"]) if state else None
    ingestion_error = ingestion_failed(db)
    return {"ready": bool(state), "updated_at": updated.isoformat() if updated else None,
            "stale": bool(ingestion_error) or not updated or db.query(QueueDirty.lead_id).first() is not None}


def read_model_active(db):
    if os.getenv("WORK_QUEUE_READ_MODEL", "auto").strip().lower() == "false":
        return False
    # Keep the existing path during initial preparation. Once published, saved
    # results remain available even if a subsequent worker run is delayed.
    return bool(checkpoint(db, "published"))


def read_queue(db, kind, category, rep="", company="", limit=50, offset=0):
    meta = status(db)
    counts = {"new": 0, "overdue": 0} if kind == "first" else {"all": 0, "overdue": 0}
    if not meta["ready"]:
        return {"items": [], "counts": counts, "global_counts": counts, "has_more": False,
                "filter_options": {"reps": [], "companies": []}, **meta}
    query = db.query(QueueLead).filter(QueueLead.first_category != "" if kind == "first" else QueueLead.followup.is_(True))

    def totals(q):
        if kind == "first":
            found = dict(q.with_entities(QueueLead.first_category, func.count()).group_by(QueueLead.first_category).all())
            return {key: found.get(key, 0) for key in ("new", "overdue")}
        total, overdue = q.with_entities(func.count(), func.count().filter(QueueLead.overdue.is_(True))).one()
        return {"all": total, "overdue": overdue}

    global_counts = totals(query)
    options = query.with_entities(QueueLead.rep, QueueLead.company).distinct().all() if kind == "followup" else []
    if rep:
        # Preserve existing first-contact matching (Unassigned is the filter label).
        if kind == "first":
            query = query.filter(QueueLead.rep == ("" if rep == "Unassigned" else rep))
        else:
            query = query.filter(func.lower(func.trim(QueueLead.rep)) == rep.strip().casefold())
    if company:
        query = query.filter(QueueLead.company == company) if kind == "first" else query.filter(func.lower(func.trim(QueueLead.company)) == company.strip().casefold())
    counts = totals(query) if rep or company else global_counts
    if kind == "first":
        query = query.filter(QueueLead.first_category == category)
        ordering = QueueLead.crm_created_at.asc() if category == "overdue" else QueueLead.crm_created_at.desc()
    else:
        if category == "overdue":
            query = query.filter(QueueLead.overdue.is_(True))
        ordering = QueueLead.created_at.desc()
    payload = QueueLead.first_payload if kind == "first" else QueueLead.followup_payload
    page = query.with_entities(payload).order_by(ordering, QueueLead.lead_id).offset(offset).limit(limit + 1).all()
    items = [json.loads(row[0]) for row in page[:limit]]
    return {"items": items, "counts": counts, "global_counts": global_counts,
            "total": counts[category], "has_more": len(page) > limit,
            "filter_options": {"reps": sorted({rep for rep, _ in options if rep}),
                               "companies": sorted({company for _, company in options if company})}, **meta}


def read_previews(db, states):
    if not states:
        return {}
    ids = {state.message_id for state in states}
    result = {}
    for row in db.query(QueueActivity).filter(QueueActivity.source != "calls", QueueActivity.message_id.in_(ids), QueueActivity.deleted.is_(False)).all():
        item = json.loads(row.payload)
        channel = "sms" if row.source == "sms_messages" else str(item.get("platform") or "messenger").strip().lower()
        result[(channel, row.message_id)] = item
    return result
