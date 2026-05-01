import logging
from mangum import Mangum
from main import app
from database import SessionLocal
from routes.assignment import _run_backlog_core

logger = logging.getLogger("moving-crm")
_mangum_handler = Mangum(app, lifespan="off")


def handler(event, context):
    # EventBridge Scheduler invokes Lambda directly (no routeKey/rawPath)
    source = event.get("source") or event.get("detail-type") or ""
    if not event.get("routeKey") and not event.get("httpMethod"):
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
    return _mangum_handler(event, context)
