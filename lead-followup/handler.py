"""Lambda entry point — lead followup system.

Triggered by EventBridge schedule. Reads new leads from Google Sheet,
checks their SmartMoving status, and sends followup SMS via Aircall.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    from services.followup import run

    days_back = event.get("days_back", 1)
    limit = event.get("limit", 0)

    logger.info("Starting lead followup: days_back=%s, limit=%s", days_back, limit)
    result = run(days_back=days_back, limit=limit)
    logger.info("Followup complete: %s", json.dumps(result["stats"]))

    return {
        "statusCode": 200,
        "body": json.dumps(result, default=str),
    }
