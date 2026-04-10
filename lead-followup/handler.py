"""Lambda entry point — lead followup system.

Triggered by EventBridge schedule. Reads new leads from CRM database,
checks their SmartMoving status, and sends followup SMS via Aircall.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    from services.followup import run

    limit = event.get("limit", 0)
    dry_run = event.get("dry_run", False)

    # Single days_back for manual testing, otherwise run day-1 and day-3
    if "days_back" in event:
        followup_days = [event["days_back"]]
    else:
        followup_days = [1, 2]  # day-2 and day-3 followups

    all_results = {}
    for days_back in followup_days:
        day_label = "Day 2" if days_back == 1 else "Day 3"
        result = run(days_back=days_back, limit=limit, dry_run=dry_run)

        # Log a clean list per day
        try:
            lines = [f"\n=== {day_label} followup ({len(result['results'])} leads) ==="]
            lines.append(f"{'Name':<25} {'Phone':<15} {'Status':<15} {'Sent'}")
            lines.append("-" * 62)
            for r in result["results"]:
                name = r.get("name", "")[:24]
                phone = r.get("phone", "")[:14]
                status = r.get("lead_status") or r.get("result", "")[:14]
                sms = r.get("sms")
                sent = "yes" if sms and sms.get("sent") else "no"
                lines.append(f"{name:<25} {phone:<15} {status:<15} {sent}")
            logger.info("\n".join(lines))
        except Exception:
            logger.exception("Error formatting log table")

        all_results[f"days_back_{days_back}"] = result

    return {
        "statusCode": 200,
        "body": json.dumps(all_results, default=str),
    }
