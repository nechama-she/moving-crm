import json
import logging
from typing import Any

from database import SessionLocal
from models import LeadUpdateLog

logger = logging.getLogger("moving-crm")


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps({"unserializable_value": repr(value)})


def record_lead_update_log(
    *,
    lead_id: str,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
    source: str = "api",
    method: str,
    endpoint: str,
    event_type: str = "lead_update",
    request_payload: Any = None,
    external_response: Any = None,
    response_status: int | None = None,
    error: str | None = None,
) -> None:
    if not lead_id:
        return

    db = SessionLocal()
    try:
        db.add(LeadUpdateLog(
            lead_id=lead_id,
            actor_user_id=actor_user_id or None,
            actor_name=actor_name or None,
            source=source,
            method=method,
            endpoint=endpoint,
            event_type=event_type,
            request_payload=_serialize(request_payload),
            external_response=_serialize(external_response),
            response_status=response_status,
            error=error or None,
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not persist lead update log for lead %s", lead_id)
    finally:
        db.close()
