"""Independent activity projection consumer; does not alter conversation state."""
import logging
import hashlib
from datetime import datetime
from boto3.dynamodb.types import TypeDeserializer

from work_queue_store import SOURCES, ingest_activity, save_checkpoint
from work_queue_models import QueueCheckpoint

logger = logging.getLogger("moving-crm.queue-stream")
deserialize = TypeDeserializer().deserialize


def failure_key(record):
    identity = f'{record.get("eventSourceARN", "")}:{record["dynamodb"]["SequenceNumber"]}'
    return "ingestion_error:" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def consume_with_recovery(db, record):
    consume(db, record)
    # A successful retry clears only its own failure. Other failed records
    # continue blocking initial activation until their retries succeed too.
    db.query(QueueCheckpoint).filter(QueueCheckpoint.key == failure_key(record)).delete()


def consume(db, record):
    arn = str(record.get("eventSourceARN") or "")
    source = next((name for name in SOURCES if f":table/{name}/stream/" in arn), None)
    if not source:
        raise ValueError("Unsupported queue activity source")
    stream = record.get("dynamodb") or {}
    raw = stream.get("NewImage") or stream.get("OldImage") or stream.get("Keys") or {}
    item = {key: deserialize(value) for key, value in raw.items()}
    deleted = record.get("eventName") == "REMOVE"
    if not deleted and item.get("record_type") != ("call" if source == "calls" else "message"):
        return
    occurred = stream.get("ApproximateCreationDateTime", 0)
    if isinstance(occurred, datetime):
        occurred = occurred.timestamp()
    ingest_activity(db, source, item, sequence=stream["SequenceNumber"], event_time=occurred, deleted=deleted)


def handler(event, context):
    from database import SessionLocal
    failures = []
    with SessionLocal() as db:
        for record in event.get("Records", []):
            try:
                with db.begin_nested():
                    consume_with_recovery(db, record)
            except Exception:
                logger.exception("Queue activity projection failed")
                # Persist failures separately so automatic retries can recover
                # without hiding unrelated failed or discarded records.
                try:
                    with db.begin_nested():
                        save_checkpoint(db, failure_key(record), {"sequence": record["dynamodb"]["SequenceNumber"],
                                                               "source": record.get("eventSourceARN", "")})
                except Exception:
                    logger.exception("Could not persist queue degradation marker")
                failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
        # One transaction delivers one coalesced notification for the batch.
        # A failed commit raises so Lambda retries the whole batch.
        db.commit()
    return {"batchItemFailures": failures}
