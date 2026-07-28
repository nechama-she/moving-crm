import json
import logging
from contextvars import ContextVar, Token
from typing import Any

from sqlalchemy import event

from database import SessionLocal, engine
from models import LeadUpdateLog

logger = logging.getLogger("moving-crm")
_captured_sql: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "lead_audit_captured_sql",
    default=None,
)


def begin_sql_capture() -> Token:
    return _captured_sql.set([])


def finish_sql_capture(token: Token) -> list[dict[str, Any]]:
    statements = list(_captured_sql.get() or [])
    _captured_sql.reset(token)
    return statements


@event.listens_for(engine, "before_cursor_execute")
def _capture_lead_write_sql(
    _connection,
    _cursor,
    statement,
    parameters,
    _context,
    executemany,
) -> None:
    captured = _captured_sql.get()
    if captured is None:
        return
    operation = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
    if operation not in {"INSERT", "UPDATE", "DELETE"}:
        return
    if "lead_update_logs" in statement.lower():
        return
    captured.append(
        {
            "statement": statement,
            "parameters": parameters,
            "executemany": bool(executemany),
        }
    )


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
    sql_statements: Any = None,
) -> str | None:
    if not lead_id:
        return None

    db = SessionLocal()
    try:
        row = LeadUpdateLog(
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
            sql_statements=_serialize(sql_statements),
        )
        db.add(row)
        db.flush()
        log_id = row.id
        db.commit()
        return log_id
    except Exception:
        db.rollback()
        logger.exception("Could not persist lead update log for lead %s", lead_id)
        return None
    finally:
        db.close()
