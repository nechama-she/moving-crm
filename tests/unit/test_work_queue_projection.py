"""Read-model regressions. Run in the dev pipeline, not against production data."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from models import Base, Company, Lead
from work_queue_models import QueueActivity, QueueDirty, QueueLead
from work_queue_store import checkpoint, ingest_activity, read_model_active, read_queue, save_checkpoint
from work_queue_worker import bootstrap_page, process_one, project_lead, run
from work_queue_stream import consume_with_recovery, failure_key
from boto3.dynamodb.types import TypeSerializer


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def activity(timestamp=1700000000, **overrides):
    return {"record_type": "call", "message_id": "call-1", "phone_number": "12125550100",
            "company_number": "2125550200", "timestamp": timestamp, "direction": "outbound", **overrides}


def seed(db, now):
    company = Company(id="company", name="Movers", phone="2125550200", timezone="America/New_York")
    lead = Lead(id="lead", full_name="Client", company=company, phone="2125550100", priority=0,
                status="new", created_at=now - timedelta(minutes=20))
    db.add_all([company, lead])
    db.commit()
    return lead


def test_replay_and_backfill_cannot_overwrite_new_activity(db):
    item = activity()
    assert ingest_activity(db, "calls", item, sequence=2, event_time=100)
    assert not ingest_activity(db, "calls", activity(direction="inbound"), sequence=1, event_time=99)
    assert not ingest_activity(db, "calls", activity(direction="inbound"), bootstrap=True)
    assert not ingest_activity(db, "calls", item, sequence=2, event_time=100)
    db.commit()
    assert db.query(QueueActivity).count() == 1
    assert json.loads(db.query(QueueActivity).one().payload)["direction"] == "outbound"


def test_delete_tombstone_prevents_backfill_resurrection(db):
    assert ingest_activity(db, "calls", activity(), sequence=3, event_time=101, deleted=True)
    assert not ingest_activity(db, "calls", activity(), bootstrap=True)
    db.commit()
    assert db.query(QueueActivity).one().deleted


def test_numeric_source_keys_are_canonical(db):
    assert ingest_activity(db, "calls", activity(timestamp="1700000000.0"), bootstrap=True)
    assert not ingest_activity(db, "calls", activity(timestamp=1700000000), bootstrap=True)


def test_checkpoint_resumes_without_replaying_first_source_page(db):
    table = Mock()
    table.scan.side_effect = [
        {"Items": [activity()], "LastEvaluatedKey": {"phone_number": "12125550100", "timestamp": 1700000000}},
        {"Items": []},
    ]
    assert not bootstrap_page(db, "calls", table)
    assert bootstrap_page(db, "calls", table)
    assert table.scan.call_args.kwargs["ExclusiveStartKey"]["timestamp"] == 1700000000
    assert bootstrap_page(db, "calls", table)
    assert table.scan.call_count == 2
    assert checkpoint(db, "bootstrap:calls")["done"]


def test_initialization_is_not_a_completed_empty_queue(db):
    response = read_queue(db, "first", "new")
    assert response["ready"] is False
    assert response["updated_at"] is None
    assert response["stale"] is True


def test_automatic_switch_waits_for_complete_build_and_survives_delays(db, monkeypatch):
    monkeypatch.delenv("WORK_QUEUE_READ_MODEL", raising=False)
    assert not read_model_active(db)
    save_checkpoint(db, "published", {"updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
    db.commit()
    assert read_model_active(db)
    # Event-driven results do not expire merely because the system is idle.
    assert not read_queue(db, "first", "new")["stale"]
    dirty = QueueDirty(lead_id="pending-lead")
    db.add(dirty)
    db.commit()
    # Keep serving saved results while a real change waits for processing.
    assert read_model_active(db)
    assert read_queue(db, "first", "new")["stale"]
    db.delete(dirty)
    db.commit()
    assert not read_queue(db, "first", "new")["stale"]
    monkeypatch.setenv("WORK_QUEUE_READ_MODEL", "false")
    assert not read_model_active(db)


def test_contact_and_deadline_change_saved_membership(db):
    now = datetime(2026, 10, 14, 15, tzinfo=timezone.utc)
    lead = seed(db, now)
    tracking = now - timedelta(days=2)
    first = project_lead(db, lead, tracking, now)
    assert first["first_category"] == "new"
    assert first["next_due_at"] <= now + timedelta(minutes=10, microseconds=1)
    later = project_lead(db, lead, tracking, now + timedelta(minutes=11))
    assert later["first_category"] == "overdue"
    ingest_activity(db, "calls", activity(timestamp=int(now.timestamp())), sequence=1, event_time=now.timestamp())
    db.commit()
    assert db.get(QueueDirty, lead.id) is not None
    assert process_one(db, tracking, now)
    assert db.get(QueueLead, lead.id).first_category == ""
    assert db.get(QueueDirty, lead.id) is None


def test_wrong_destination_does_not_complete_first_contact(db):
    now = datetime(2026, 10, 14, 15, tzinfo=timezone.utc)
    lead = seed(db, now)
    ingest_activity(db, "calls", activity(timestamp=int(now.timestamp()), company_number="9995550200"), bootstrap=True)
    db.commit()
    assert project_lead(db, lead, now - timedelta(days=1), now)["first_category"] == "new"


def test_deleted_lead_is_removed_without_touching_source_activity(db):
    now = datetime(2026, 10, 14, 15, tzinfo=timezone.utc)
    lead = seed(db, now)
    values = project_lead(db, lead, now - timedelta(days=1), now)
    db.add(QueueLead(**values))
    db.add(QueueDirty(lead_id=lead.id))
    db.delete(lead)
    db.commit()
    assert process_one(db, now - timedelta(days=1), now)
    assert db.query(QueueLead).count() == 0


def test_ready_counts_and_pagination_use_saved_rows(db):
    now = datetime.now(timezone.utc)
    lead = seed(db, now)
    db.add(QueueLead(**project_lead(db, lead, now - timedelta(days=1), now)))
    save_checkpoint(db, "published", {"updated_at": now.isoformat()})
    db.commit()
    response = read_queue(db, "first", "new", rep="Unassigned", limit=1)
    assert response["ready"]
    assert response["counts"] == {"new": 1, "overdue": 0}
    assert response["items"][0]["lead_id"] == lead.id
    assert not response["has_more"]
    assert read_queue(db, "first", "new", company="Other")["items"] == []
    assert read_queue(db, "first", "new", offset=1)["items"] == []


def test_failed_ingestion_does_not_look_fresh(db):
    now = datetime.now(timezone.utc)
    save_checkpoint(db, "published", {"updated_at": now.isoformat()})
    save_checkpoint(db, "ingestion_error", {"sequence": "123"})
    db.commit()
    response = read_queue(db, "followup", "all")
    assert response["ready"]
    assert response["stale"]


def test_retry_recovers_its_own_failure_without_hiding_another(db):
    serializer = TypeSerializer()
    record = {"eventSourceARN": "arn:aws:dynamodb:us-east-1:123:table/calls/stream/test", "eventName": "INSERT",
              "dynamodb": {"SequenceNumber": "123", "ApproximateCreationDateTime": 1700000001,
                           "NewImage": {key: serializer.serialize(value) for key, value in activity().items()}}}
    save_checkpoint(db, failure_key(record), {"sequence": "123"})
    save_checkpoint(db, "ingestion_error:other", {"sequence": "other"})
    db.commit()
    consume_with_recovery(db, record)
    db.commit()
    assert checkpoint(db, failure_key(record)) is None
    assert checkpoint(db, "ingestion_error:other") is not None


def test_idle_replay_does_not_publish_another_update(db):
    for source in ("calls", "sms_messages", "conversations"):
        save_checkpoint(db, "bootstrap:" + source, {"done": True})
    seed(db, datetime.now(timezone.utc))
    db.commit()
    tables = {source: Mock() for source in ("calls", "sms_messages", "conversations")}
    first = run(db, tables)
    assert first["processed"] == 1
    published = checkpoint(db, "published")
    assert published
    assert run(db, tables)["processed"] == 0
    assert checkpoint(db, "published") == published
    for table in tables.values():
        table.scan.assert_not_called()


def test_retry_after_final_row_commit_still_publishes(db):
    for source in ("calls", "sms_messages", "conversations"):
        save_checkpoint(db, "bootstrap:" + source, {"done": True})
    save_checkpoint(db, "tracking", {"start": None})
    old = {"updated_at": "2020-01-01T00:00:00+00:00"}
    save_checkpoint(db, "published", old)
    save_checkpoint(db, "projection_pending", {"updated_at": "2026-01-01T00:00:00+00:00"})
    db.commit()
    assert run(db, {source: Mock() for source in ("calls", "sms_messages", "conversations")})["processed"] == 0
    assert checkpoint(db, "published") != old
    assert checkpoint(db, "projection_pending") is None
