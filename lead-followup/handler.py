"""Lambda entry point — lead followup system.

Triggered by EventBridge schedule. Reads new leads from CRM database,
checks their SmartMoving status, and sends followup SMS via Aircall.
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    mode = event.get("mode", "all")
    dry_run = event.get("dry_run", False)
    all_results = {}

    # --- Day 2 & Day 3 followups ---
    if mode in ("all", "day_followup"):
        from services.followup import run

        limit = event.get("limit", 0)

        # Single days_back for manual testing, otherwise run day-1 and day-3
        if "days_back" in event:
            followup_days = [event["days_back"]]
        else:
            followup_days = [1, 2]  # day-2 and day-3 followups

        for days_back in followup_days:
            day_label = "Day 2" if days_back == 1 else "Day 3"
            result = run(days_back=days_back, limit=limit, dry_run=dry_run)

            # Log a clean list per day
            try:
                run_mode = "DRY RUN" if dry_run else "LIVE"
                lines = [f"\n=== {day_label} followup [{run_mode}] ({len(result['results'])} leads) ==="]
                for w in result.get("windows", []):
                    lines.append(f"  {w['company']} ({w['timezone']}): {w['local_start']} → {w['local_end']} local | {w['window_start']} → {w['window_end']} UTC")
                lines.append(f"{'Name':<25} {'Phone':<15} {'Created (local)':<20} {'Created (UTC)':<20} {'Status':<15} {'Qualifies':<10} {'Sent'}")
                lines.append("-" * 115)
                for r in result["results"]:
                    name = r.get("name", "")[:24]
                    phone = r.get("phone", "")[:14]
                    created_utc = r.get("created_at", "")
                    created_utc_str = str(created_utc)[:19] if created_utc else ""
                    # Convert to local time
                    created_local_str = ""
                    if created_utc and r.get("company_timezone"):
                        try:
                            utc_dt = created_utc if isinstance(created_utc, datetime) else datetime.fromisoformat(str(created_utc))
                            local_dt = utc_dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(r["company_timezone"]))
                            created_local_str = local_dt.strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            created_local_str = created_utc_str
                    status = r.get("lead_status") or r.get("result", "")[:14]
                    qualifies = "yes" if r.get("qualifies") else "no"
                    sms = r.get("sms")
                    if sms and sms.get("sent"):
                        sent = "yes"
                    elif sms and sms.get("dry_run"):
                        sent = "dry_run"
                    else:
                        sent = "no"
                    lines.append(f"{name:<25} {phone:<15} {created_local_str:<20} {created_utc_str:<20} {status:<15} {qualifies:<10} {sent}")
                if not result["results"]:
                    lines.append("(no leads in window)")
                logger.info("\n".join(lines))
            except Exception:
                logger.exception("Error formatting log table")

            all_results[f"days_back_{days_back}"] = result

    # --- Daily followup messages ---
    if mode in ("all", "followup_messages"):
        from services.followup_messages import run_followup_messages
        followup_msg_dry_run = event.get("followup_messages_dry_run", True)
        followup_msg_smartmoving_id = event.get("followup_messages_smartmoving_id") or None
        followup_msg_result = run_followup_messages(dry_run=followup_msg_dry_run, smartmoving_id=followup_msg_smartmoving_id)
        all_results["followup_messages"] = followup_msg_result

        run_mode = "DRY RUN" if followup_msg_dry_run else "LIVE"
        logger.info(
            "\n=== Followup Messages [%s] ===\nTotal: %d | Processed: %d | Notes updated: %d | Notes failed: %d",
            run_mode,
            followup_msg_result["stats"]["total"],
            followup_msg_result["stats"]["processed"],
            followup_msg_result["stats"]["note_updated"],
            followup_msg_result["stats"]["note_failed"],
        )

    return {
        "statusCode": 200,
        "body": json.dumps(all_results, default=str),
    }
