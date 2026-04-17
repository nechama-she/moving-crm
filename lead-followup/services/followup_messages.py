"""Followup message service — sends messages for due followups and updates SmartMoving notes."""

import logging
from datetime import datetime, timezone

from database import get_due_followups, was_already_sent, record_sent_message
from libs.aircall import send_sms, find_number_id
from libs.smartmoving import update_followup

logger = logging.getLogger(__name__)

DRY_RUN_MESSAGE = "sample test followup message"


def _build_channels(row: dict) -> list[str]:
    """Determine which channels to use for this followup."""
    channels = []
    if row.get("phone"):
        channels.append("aircall")
    if row.get("facebook_user_id"):
        channels.append("messenger")
    return channels


def _send_aircall(row: dict, message: str, dry_run: bool) -> dict:
    phone = str(row["phone"]).strip()
    aircall_number_id = row.get("aircall_number_id")
    company_phone = row.get("company_phone", "")

    if dry_run:
        return {"channel": "aircall", "sent": False, "dry_run": True, "would_send_to": phone, "message": message}

    nid = aircall_number_id
    if not nid and company_phone:
        nid = find_number_id(company_phone)

    result = send_sms(to=phone, text=message, number_id=nid)
    if result["ok"]:
        return {"channel": "aircall", "sent": True, "to": phone, "message": message}
    return {"channel": "aircall", "sent": False, "error": result.get("error"), "message": message}


def _send_messenger(row: dict, message: str, dry_run: bool) -> dict:
    user_id = str(row["facebook_user_id"]).strip()

    if dry_run:
        return {"channel": "messenger", "sent": False, "dry_run": True, "would_send_to": user_id, "message": message}

    # Import here to avoid circular / missing dependency issues
    # Messenger sending is handled by the CRM backend, not this Lambda
    # For now, dry_run only
    return {"channel": "messenger", "sent": False, "dry_run": True, "would_send_to": user_id, "message": message}


def _update_smartmoving_note(row: dict, message: str, channels_results: list[dict]) -> dict:
    """Update the followup note in SmartMoving with the message that was (or would be) sent."""
    existing_notes = row.get("notes") or ""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    channels_summary = []
    for ch in channels_results:
        status = "SENT" if ch.get("sent") else "DRY_RUN"
        channels_summary.append(f"{ch['channel']}: {status}")

    new_note = f"[Followup {timestamp}] ({', '.join(channels_summary)}) {message}"
    updated_notes = f"{existing_notes}\n{new_note}".strip() if existing_notes else new_note

    payload = {
        "type": row.get("type"),
        "title": row.get("title") or "",
        "assignedToId": row.get("assigned_to_id") or "",
        "dueDateTime": row["due_date_time"].isoformat() if row.get("due_date_time") else "",
        "completedAtUtc": row["completed_at_utc"].isoformat() if row.get("completed_at_utc") else None,
        "notes": updated_notes,
        "completed": row.get("completed") or False,
    }

    result = update_followup(
        opportunity_id=row["smartmoving_id"],
        followup_id=row["note_id"],
        payload=payload,
    )
    return result


def run_followup_messages(dry_run: bool = True) -> dict:
    """Main entry: find due followups, send messages, update SmartMoving notes."""
    if dry_run:
        logger.info("*** DRY RUN — messages will NOT be sent ***")

    rows = get_due_followups()
    logger.info("Found %d due followups", len(rows))

    results = []
    stats = {"total": len(rows), "processed": 0, "note_updated": 0, "note_failed": 0}

    for row in rows:
        name = row.get("full_name", "").strip()
        note_id = row["note_id"]
        sm_id = str(row["smartmoving_id"])
        msg_type = f"followup_{note_id}"
        channels = _build_channels(row)

        if not channels:
            logger.info("Followup %s (%s): no channels available, skipping", note_id, name)
            results.append({"note_id": note_id, "name": name, "result": "no_channels"})
            continue

        # Dedup: skip entirely if SmartMoving note already updated for this followup
        if was_already_sent(sm_id, msg_type, "smartmoving_note"):
            logger.info("SKIP %s (%s): followup %s already processed", name, sm_id, note_id)
            results.append({"note_id": note_id, "name": name, "result": "already_sent"})
            continue

        message = DRY_RUN_MESSAGE
        channels_results = []

        for ch in channels:
            if was_already_sent(sm_id, msg_type, ch):
                logger.info("SKIP %s channel %s for followup %s: already sent", name, ch, note_id)
                channels_results.append({"channel": ch, "sent": False, "skipped": True, "reason": "already_sent"})
                continue
            if ch == "aircall":
                result = _send_aircall(row, message, dry_run)
                channels_results.append(result)
                if result.get("sent"):
                    record_sent_message(sm_id, msg_type, "aircall")
            elif ch == "messenger":
                result = _send_messenger(row, message, dry_run)
                channels_results.append(result)
                if result.get("sent"):
                    record_sent_message(sm_id, msg_type, "messenger")

        # Always update SmartMoving note (not dry run)
        note_result = _update_smartmoving_note(row, message, channels_results)
        if note_result.get("ok"):
            stats["note_updated"] += 1
            record_sent_message(sm_id, msg_type, "smartmoving_note")
        else:
            stats["note_failed"] += 1

        stats["processed"] += 1
        results.append({
            "note_id": note_id,
            "name": name,
            "smartmoving_id": sm_id,
            "channels": channels_results,
            "note_update": note_result,
        })

        logger.info(
            "Followup %s (%s): channels=%s, note_update=%s",
            note_id, name, [c["channel"] for c in channels_results],
            "ok" if note_result.get("ok") else note_result.get("error", "failed"),
        )

    return {"stats": stats, "results": results}
