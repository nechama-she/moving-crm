import logging
from mangum import Mangum
from main import app
from database import SessionLocal
from routes.assignment import _run_backlog_core, _get_default_run_mode

# Force INFO logs in Lambda so scheduler diagnostics are visible in CloudWatch.
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
logging.getLogger("moving-crm").setLevel(logging.INFO)
logger = logging.getLogger("moving-crm")
_mangum_handler = Mangum(app, lifespan="off")


def _is_scheduler_backlog_invoke(event: dict) -> bool:
    """Only run backlog for explicit scheduler payloads."""
    trigger = str(event.get("trigger") or "").strip().lower()
    job = str(event.get("job") or "").strip().lower()
    if trigger == "auto_assign_backlog" or job == "auto_assign_backlog":
        return True

    # Backward-compatible support for EventBridge rule-style envelopes.
    source = str(event.get("source") or "").strip().lower()
    detail_type = str(event.get("detail-type") or "").strip().lower()
    if source in {"aws.scheduler", "aws.events"} and detail_type.startswith("scheduled"):
        return True

    return False


def _header_value(event: dict, name: str) -> str:
    headers = event.get("headers") or {}
    return str(headers.get(name) or headers.get(name.lower()) or "")


def _optional_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return None


def handler(event, context):
    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}
    route_key = event.get("routeKey") or request_context.get("routeKey")
    method = event.get("httpMethod") or http_context.get("method")
    path = event.get("rawPath") or http_context.get("path") or event.get("path")
    source = str(event.get("source") or event.get("detail-type") or "")

    if method or route_key or path:
        logger.info(
            "HTTP invoke: method=%s path=%s route=%s source_ip=%s user_agent=%s request_id=%s",
            method or "",
            path or "",
            route_key or "",
            http_context.get("sourceIp") or _header_value(event, "x-forwarded-for"),
            http_context.get("userAgent") or _header_value(event, "user-agent"),
            getattr(context, "aws_request_id", ""),
        )
        return _mangum_handler(event, context)

    if not _is_scheduler_backlog_invoke(event):
        logger.warning(
            "Ignoring unknown non-HTTP invoke: keys=%s request_id=%s",
            sorted(list(event.keys())),
            getattr(context, "aws_request_id", ""),
        )
        print(
            "[scheduler] ignored non-http invoke keys=%s request_id=%s"
            % (sorted(list(event.keys())), getattr(context, "aws_request_id", ""))
        )
        return {"ok": False, "ignored": True, "reason": "unknown_non_http_event"}

    logger.info(
        "Non-HTTP invoke treated as scheduler: source=%s keys=%s request_id=%s",
        source,
        sorted(list(event.keys())),
        getattr(context, "aws_request_id", ""),
    )
    print(
        "[scheduler] invoke source=%s keys=%s request_id=%s"
        % (
            source,
            sorted(list(event.keys())),
            getattr(context, "aws_request_id", ""),
        )
    )
    logger.info("Scheduler trigger detected — running backlog assignment")
    db = SessionLocal()
    try:
        event_dry_run = _optional_bool(event.get("dry_run"))
        if event_dry_run is None:
            mode = _get_default_run_mode(db)
            dry_run = mode == "dry"
        else:
            dry_run = event_dry_run
        logger.info("Scheduler resolved run mode: dry_run=%s", dry_run)
        result = _run_backlog_core(db, dry_run=dry_run)
        logger.info("Scheduler backlog result: %s", result)
        print("[scheduler] backlog result=%s" % result)
    except Exception as exc:
        logger.exception("Scheduler backlog run failed")
        print("[scheduler] backlog failed: %s" % exc)
        raise
    finally:
        db.close()
    return {"ok": True}
