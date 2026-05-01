import logging
from mangum import Mangum
from main import app
from database import SessionLocal
from routes.assignment import _run_backlog_core

logger = logging.getLogger("moving-crm")
_mangum_handler = Mangum(app, lifespan="off")


def _header_value(event: dict, name: str) -> str:
    headers = event.get("headers") or {}
    return str(headers.get(name) or headers.get(name.lower()) or "")


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

    # EventBridge invokes Lambda directly (no routeKey/rawPath)
    if source.startswith("aws.events") or source.startswith("aws.scheduler"):
        logger.info(
            "EventBridge invoke: source=%s resources=%s request_id=%s",
            source,
            event.get("resources") or [],
            getattr(context, "aws_request_id", ""),
        )
        logger.info("Scheduler trigger detected — running backlog assignment")
        db = SessionLocal()
        try:
            result = _run_backlog_core(db, dry_run=False)
            logger.info("Scheduler backlog result: %s", result)
        except Exception as exc:
            logger.error("Scheduler backlog run failed: %s", exc)
        finally:
            db.close()
        return {"ok": True}

    logger.warning(
        "Unknown non-HTTP invoke; forwarding to Mangum: source=%s keys=%s request_id=%s",
        source,
        sorted(list(event.keys())),
        getattr(context, "aws_request_id", ""),
    )
    return _mangum_handler(event, context)
