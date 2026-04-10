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
            mode = "DRY RUN" if dry_run else "LIVE"
            lines = [f"\n=== {day_label} followup [{mode}] ({len(result['results'])} leads) ==="]
            for w in result.get("windows", []):
                lines.append(f"  {w['company']} ({w['timezone']}): {w['local_start']} → {w['local_end']} local | {w['window_start']} → {w['window_end']} UTC")
            lines.append(f"{'Name':<25} {'Phone':<15} {'Created':<20} {'Status':<15} {'Qualifies':<10} {'Sent'}")
            lines.append("-" * 95)
            for r in result["results"]:
                name = r.get("name", "")[:24]
                phone = r.get("phone", "")[:14]
                created = str(r.get("created_at", ""))[:19]
                status = r.get("lead_status") or r.get("result", "")[:14]
                qualifies = "yes" if r.get("qualifies") else "no"
                sms = r.get("sms")
                if sms and sms.get("sent"):
                    sent = "yes"
                elif sms and sms.get("dry_run"):
                    sent = "dry_run"
                else:
                    sent = "no"
                lines.append(f"{name:<25} {phone:<15} {created:<20} {status:<15} {qualifies:<10} {sent}")
            if not result["results"]:
                lines.append("(no leads in window)")
            logger.info("\n".join(lines))
        except Exception:
            logger.exception("Error formatting log table")

        all_results[f"days_back_{days_back}"] = result

    return {
        "statusCode": 200,
        "body": json.dumps(all_results, default=str),
    }
