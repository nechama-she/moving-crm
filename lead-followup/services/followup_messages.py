"""Followup message service — sends messages for due followups and updates SmartMoving notes."""

import logging
import os
import re
from datetime import datetime, timezone

import httpx

from database import (
    get_due_followups,
    was_already_sent,
    record_sent_message,
    record_outreach_event,
    sync_followup_from_smartmoving,
    get_sales_rep_number,
)
from libs.aircall import send_sms, find_number_id
from libs.common.ssm import get_ssm_cached
from libs.smartmoving import get_followup, get_opportunity, update_followup, reset_request_counters, get_request_counters

logger = logging.getLogger(__name__)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_KEY_SSM_PATH = "/meta-webhook/OPENAI_API_KEY"

OPTION_1 = (
    "Hi {name}, hope all is well! Do you have any updates on your moving plans, "
    "or would you like to go ahead and schedule the move?"
)
OPTION_2 = "Hi {name}, are you still looking for a mover for your upcoming move?"
ALLOWED_OPPORTUNITY_STATUSES = {0, 1, 3}
ALLOWED_LEAD_PRIORITIES = {1, 2, 3, 4, 6, 7}


def _first_name(full_name: str) -> str:
    name = (full_name or "").strip()
    return name.split()[0] if name else "there"


def _build_company_signature(row: dict) -> str:
    company = (row.get("company_name") or "").strip()
    phone = (row.get("company_phone") or "").strip()
    parts = ["Thanks,"]
    if company:
        parts[-1] = f"Thanks, {company}"
    if phone:
        parts.append(phone)
    return "\n".join(parts)


def _build_signature(row: dict, opportunity: dict | None = None) -> str:
    """Use rep signature only when rep exists in sales_reps; otherwise company fallback."""
    sales_assignee = (opportunity or {}).get("salesAssignee") or {}
    rep_name = (sales_assignee.get("name") or "").strip()
    if rep_name:
        rep_number_id = get_sales_rep_number(rep_name)
        if rep_number_id:
            rep_phone = (sales_assignee.get("phone") or "").strip()
            if rep_phone:
                return f"Thanks, {rep_name}\n{rep_phone}"
            logger.info("Sales rep %s is mapped but phone was not resolved; using company signature", rep_name)
    return _build_company_signature(row)


def _ensure_signature(message: str, signature: str) -> str:
    clean_message = (message or "").strip()
    clean_signature = (signature or "").strip()
    if not clean_signature:
        return clean_message
    if clean_signature in clean_message:
        return clean_message
    return f"{clean_message}\n\n{clean_signature}".strip()


def _generate_message_from_note(row: dict, opportunity: dict | None = None) -> tuple[str | None, str]:
    api_key = os.getenv("OPENAI_API_KEY", "") or get_ssm_cached(OPENAI_KEY_SSM_PATH)
    if not api_key:
        return None, "no_openai_key"

    name = _first_name(row.get("full_name", ""))
    option_1 = OPTION_1.format(name=name)
    option_2 = OPTION_2.format(name=name)
    signature = _build_signature(row, opportunity=opportunity)
    notes = (row.get("notes") or "").strip()

    system_prompt = (
        "You will receive a note or a list of notes about a conversation with a client. "
        "Your task is to generate a short follow-up SMS message.\n\n"
        "Rules:\n"
        "- Assume the follow-up is being sent before the client completed the action they mentioned.\n"
        "- Do not ask if something still works or give the client an easy option to cancel.\n"
        "- Do not ask yes/no questions that invite them to decline.\n"
        "- The message should assume progress and gently prompt an update.\n"
        "- If the note includes a time or scheduled call, frame it as a reminder, not a confirmation.\n"
        "- If the note includes something the client needed to do (ask father, check closing date, etc.), follow up expecting an update.\n"
        "- Keep the message short, natural, and conversational, like a real text message.\n"
        "- You will be given two template options. If either option is relevant to the note, choose it (as-is or lightly adapted). If the note contains specific details that the templates cannot address (e.g. a scheduled time, a pending action the client had to take), write a custom message instead.\n"
        "- Do not introduce placeholders like [Your Name].\n"
        "- Output only the message."
    )
    user_prompt = (
        f"Lead name: {name}\n"
        f"Company: {row.get('company_name', '')}\n"
        f"Followup note:\n{notes}\n\n"
        f"Option 1:\n{option_1}\n\n"
        f"Option 2:\n{option_2}\n\n"
        "Write the SMS message body only, without a signature."
    )

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENAI_MODEL,
                    "temperature": 0.2,
                    "max_tokens": 220,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if not content:
                raise ValueError("empty_response")
            content = _ensure_signature(content, signature)
            return content, "openai"
    except Exception as exc:
        logger.warning("OpenAI generation failed: %s", exc)
        return None, "openai_error"


def _build_channels(row: dict) -> list[str]:
    """Determine which channels to use for this followup."""
    channels = []
    if row.get("phone"):
        channels.append("aircall")
    if row.get("facebook_user_id"):
        channels.append("messenger")
    return channels


def _send_aircall(row: dict, message: str, dry_run: bool, opportunity: dict | None = None) -> dict:
    phone = str(row["phone"]).strip()
    aircall_number_id = row.get("aircall_number_id")
    company_phone = row.get("company_phone", "")

    sales_assignee = (opportunity or {}).get("salesAssignee") or {}
    rep_name = (sales_assignee.get("name") or "").strip()
    rep_number_id = get_sales_rep_number(rep_name) if rep_name else None

    if dry_run:
        dry_run_number_id = rep_number_id or aircall_number_id
        logger.info(
            "Aircall DRY_RUN: would send to %s, number_id=%s, message=%s",
            phone,
            dry_run_number_id,
            message,
        )
        return {"channel": "aircall", "sent": False, "dry_run": True, "would_send_to": phone, "message": message}

    nid = rep_number_id or aircall_number_id
    if rep_number_id:
        logger.info("Using sales rep %s Aircall number %s", rep_name, rep_number_id)
    if not nid and company_phone:
        nid = find_number_id(company_phone)

    logger.info("Aircall API request: send_sms(to=%s, number_id=%s, message=%s)", phone, nid, message)
    result = send_sms(to=phone, text=message, number_id=nid)
    logger.info("Aircall API response: %s", result)
    if result["ok"]:
        return {"channel": "aircall", "sent": True, "to": phone, "message": message}
    return {"channel": "aircall", "sent": False, "error": result.get("error"), "message": message}


def _send_messenger(row: dict, message: str, dry_run: bool) -> dict:
    user_id = str(row["facebook_user_id"]).strip()

    if dry_run:
        logger.info("Messenger DRY_RUN: would send to %s, message=%s", user_id, message)
        return {"channel": "messenger", "sent": False, "dry_run": True, "would_send_to": user_id, "message": message}

    # Messenger sending is handled by the CRM backend, not this Lambda
    # For now, keep non-sending behavior in live mode as well.
    logger.info("Messenger: not yet implemented, skipping user_id=%s", user_id)
    return {"channel": "messenger", "sent": False, "dry_run": True, "would_send_to": user_id, "message": message}


def _build_followup_message_type(note_id: str, due_date_time_val) -> str:
    """Build dedup key scoped to followup note and due datetime.

    If due datetime changes, this key changes too, so it is treated as a new followup cycle.
    """
    if isinstance(due_date_time_val, datetime):
        due_key = due_date_time_val.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    else:
        due_str = str(due_date_time_val or "")
        due_key = re.sub(r"[^0-9]", "", due_str)[:14]
    if not due_key:
        due_key = "nodue"
    note_key = str(note_id or "nonote")
    return f"followup_{note_key}_{due_key}"


def _normalize_status(status_val) -> int | None:
    if status_val is None:
        return None
    try:
        return int(status_val)
    except (TypeError, ValueError):
        return None


def _parse_lead_priority(lead_status_val) -> int | None:
    """Parse leadStatus like 'Priority 1' (case-insensitive) into an int."""
    if lead_status_val is None:
        return None
    text = str(lead_status_val).strip().lower()
    match = re.search(r"priority\s*(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _should_process_opportunity(opportunity: dict) -> tuple[bool, str]:
    status_raw = opportunity.get("status")
    lead_status_raw = opportunity.get("leadStatus")

    # Safety-first: if status is missing, do nothing.
    if status_raw is None:
        return False, "missing_status_data"
    if lead_status_raw is None:
        return False, "missing_lead_status_data"

    status_num = _normalize_status(status_raw)
    if status_num is None:
        return False, "invalid_status_data"
    if status_num not in ALLOWED_OPPORTUNITY_STATUSES:
        return False, f"status_{status_num}_not_allowed"

    lead_priority = _parse_lead_priority(lead_status_raw)
    if lead_priority is None:
        return False, "invalid_lead_status_data"
    if lead_priority not in ALLOWED_LEAD_PRIORITIES:
        return False, f"priority_{lead_priority}_not_allowed"

    return True, "ok"


def _update_smartmoving_note(row: dict, live_followup: dict, message: str, channels_results: list[dict]) -> dict:
    """Update the followup note in SmartMoving with the message that was (or would be) sent."""
    sm_id = str(row["smartmoving_id"])
    note_id = str(row["note_id"])

    existing_notes = live_followup.get("notes") or ""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    channels_summary = []
    for ch in channels_results:
        status = "SENT" if ch.get("sent") else "DRY_RUN"
        channels_summary.append(f"{ch['channel']}: {status}")

    new_note = f"[Followup {timestamp}] ({', '.join(channels_summary)}) {message}"
    updated_notes = f"{existing_notes}\n{new_note}".strip() if existing_notes else new_note

    # Only update SmartMoving if all required fields have data
    required_fields = {
        "type": live_followup.get("type"),
        "title": live_followup.get("title"),
        "assignedToId": live_followup.get("assignedToId"),
        "dueDateTime": live_followup.get("dueDateTime"),
        "notes": updated_notes,
        "completed": live_followup.get("completed"),
    }
    missing = [k for k, v in required_fields.items() if v is None or v == ""]
    if missing:
        logger.warning("SKIP SmartMoving update for %s/%s: missing fields: %s",
            sm_id, note_id, missing)
        return {"ok": False, "error": f"missing_required_fields: {missing}"}

    payload = {
        "type": live_followup["type"],
        "title": live_followup["title"],
        "assignedToId": str(live_followup["assignedToId"]),
        "dueDateTime": live_followup["dueDateTime"],
        "notes": updated_notes,
        "completed": live_followup["completed"],
    }

    logger.info("SmartMoving update payload for %s/%s: %s", sm_id, note_id, payload)

    result = update_followup(
        opportunity_id=sm_id,
        followup_id=note_id,
        payload=payload,
    )

    if result.get("ok"):
        db_sync = sync_followup_from_smartmoving(
            smartmoving_id=sm_id,
            note_id=note_id,
            followup_type=payload["type"],
            title=payload["title"],
            assigned_to_id=payload["assignedToId"],
            due_date_time_iso=payload["dueDateTime"],
            notes=payload["notes"],
            completed=payload["completed"],
        )
        if not db_sync.get("ok"):
            logger.warning("DB followup sync failed for %s/%s: %s", sm_id, note_id, db_sync.get("error"))
            return {"ok": False, "error": f"db_sync_failed: {db_sync.get('error')}"}

    logger.info("SmartMoving update response for %s/%s: %s", sm_id, note_id, result)
    return result


def run_followup_messages(dry_run: bool = True, smartmoving_id: str | None = None) -> dict:
    """Main entry: find due followups, generate message, update SmartMoving notes."""
    if dry_run:
        logger.info("*** DRY RUN — messages will NOT be sent ***")
    if smartmoving_id:
        logger.info("*** Filtering to single smartmoving_id: %s ***", smartmoving_id)
    reset_request_counters()

    rows = get_due_followups(smartmoving_id=smartmoving_id)
    logger.info("Found %d due followups", len(rows))
    for i, row in enumerate(rows):
        logger.info(
            "  Followup %d: name=%s, smartmoving_id=%s, note_id=%s, phone=%s, fb=%s, due=%s",
            i + 1, row.get("full_name"), row.get("smartmoving_id"), row.get("note_id"),
            row.get("phone"), row.get("facebook_user_id"), row.get("due_date_time"),
        )

    results = []
    stats = {"total": len(rows), "processed": 0, "note_updated": 0, "note_failed": 0}
    updated_jobs = []
    failed_jobs = []

    for row in rows:
        name = row.get("full_name", "").strip()
        note_id = row["note_id"]
        sm_id = str(row["smartmoving_id"])
        channels = _build_channels(row)
        qualified = False
        qualification_reason = "ok"
        message_preview = ""

        if not channels:
            logger.info("Followup %s (%s): no channels available, skipping", note_id, name)
            qualification_reason = "no_channels"
            record_outreach_event(
                lead_id=str(row.get("lead_id") or "") or None,
                company_id=str(row.get("company_id") or "") or None,
                smartmoving_id=sm_id,
                note_id=str(note_id),
                outreach_type="due",
                job_id=sm_id,
                qualified=False,
                qualification_reason=qualification_reason,
                message="",
                messenger=False,
                aircall=False,
                dry_run=dry_run,
            )
            results.append({"note_id": note_id, "name": name, "result": "no_channels"})
            continue

        live_followup_resp = get_followup(sm_id, note_id)
        if "error" in live_followup_resp:
            logger.info("SKIP %s (%s): failed to fetch live followup (%s)", name, sm_id, live_followup_resp["error"])
            qualification_reason = f"live_fetch_failed: {live_followup_resp['error']}"
            record_outreach_event(
                lead_id=str(row.get("lead_id") or "") or None,
                company_id=str(row.get("company_id") or "") or None,
                smartmoving_id=sm_id,
                note_id=str(note_id),
                outreach_type="due",
                job_id=sm_id,
                qualified=False,
                qualification_reason=qualification_reason,
                message="",
                messenger=bool(row.get("facebook_user_id")),
                aircall=bool(row.get("phone")),
                dry_run=dry_run,
            )
            results.append({
                "note_id": note_id,
                "name": name,
                "smartmoving_id": sm_id,
                "result": "live_fetch_failed",
                "error": live_followup_resp["error"],
            })
            continue

        live_followup = live_followup_resp.get("data") or {}
        msg_type = _build_followup_message_type(note_id, live_followup.get("dueDateTime"))

        opp_resp = get_opportunity(sm_id)
        if "error" in opp_resp:
            logger.info("SKIP %s (%s): failed to fetch opportunity (%s)", name, sm_id, opp_resp["error"])
            qualification_reason = f"opportunity_fetch_failed: {opp_resp['error']}"
            record_outreach_event(
                lead_id=str(row.get("lead_id") or "") or None,
                company_id=str(row.get("company_id") or "") or None,
                smartmoving_id=sm_id,
                note_id=str(note_id),
                outreach_type="due",
                job_id=sm_id,
                qualified=False,
                qualification_reason=qualification_reason,
                message="",
                messenger=bool(row.get("facebook_user_id")),
                aircall=bool(row.get("phone")),
                dry_run=dry_run,
            )
            results.append({
                "note_id": note_id,
                "name": name,
                "smartmoving_id": sm_id,
                "result": "opportunity_fetch_failed",
                "error": opp_resp["error"],
            })
            continue

        opportunity = opp_resp.get("data") or {}
        should_process, status_reason = _should_process_opportunity(opportunity)
        if not should_process:
            logger.info("SKIP %s (%s): %s", name, sm_id, status_reason)
            qualification_reason = status_reason
            record_outreach_event(
                lead_id=str(row.get("lead_id") or "") or None,
                company_id=str(row.get("company_id") or "") or None,
                smartmoving_id=sm_id,
                note_id=str(note_id),
                outreach_type="due",
                job_id=sm_id,
                qualified=False,
                qualification_reason=qualification_reason,
                message="",
                messenger=bool(row.get("facebook_user_id")),
                aircall=bool(row.get("phone")),
                dry_run=dry_run,
            )
            results.append({
                "note_id": note_id,
                "name": name,
                "smartmoving_id": sm_id,
                "result": "skipped_status",
                "reason": status_reason,
                "smartmoving_status": opportunity.get("status"),
                "lead_status": opportunity.get("leadStatus"),
                "opportunity_status": opportunity.get("opportunityStatus"),
            })
            continue

        # Dedup: skip entirely if SmartMoving note already updated for this followup
        if was_already_sent(sm_id, msg_type, "smartmoving_note"):
            logger.info("SKIP %s (%s): followup %s already processed", name, sm_id, note_id)
            record_outreach_event(
                lead_id=str(row.get("lead_id") or "") or None,
                company_id=str(row.get("company_id") or "") or None,
                smartmoving_id=sm_id,
                note_id=str(note_id),
                outreach_type="due",
                job_id=sm_id,
                qualified=True,
                qualification_reason="already_sent",
                message="",
                messenger=bool(row.get("facebook_user_id")),
                aircall=bool(row.get("phone")),
                dry_run=dry_run,
            )
            results.append({"note_id": note_id, "name": name, "result": "already_sent"})
            continue

        message, message_source = _generate_message_from_note(row, opportunity=opportunity)
        if not message:
            logger.info("SKIP %s (%s): no AI message generated (%s)", name, sm_id, message_source)
            qualification_reason = "no_ai_message"
            record_outreach_event(
                lead_id=str(row.get("lead_id") or "") or None,
                company_id=str(row.get("company_id") or "") or None,
                smartmoving_id=sm_id,
                note_id=str(note_id),
                outreach_type="due",
                job_id=sm_id,
                qualified=True,
                qualification_reason=qualification_reason,
                message="",
                messenger=bool(row.get("facebook_user_id")),
                aircall=bool(row.get("phone")),
                dry_run=dry_run,
            )
            results.append({
                "note_id": note_id,
                "name": name,
                "smartmoving_id": sm_id,
                "result": "skipped_no_ai_message",
                "message_source": message_source,
            })
            continue
        qualified = True
        message_preview = message
        channels_results = []

        for ch in channels:
            if was_already_sent(sm_id, msg_type, ch):
                logger.info("SKIP %s channel %s for followup %s: already sent", name, ch, note_id)
                channels_results.append({"channel": ch, "sent": False, "skipped": True, "reason": "already_sent"})
                continue
            if ch == "aircall":
                result = _send_aircall(row, message, dry_run, opportunity=opportunity)
                channels_results.append(result)
                if result.get("sent"):
                    record_sent_message(sm_id, msg_type, "aircall")
            elif ch == "messenger":
                result = _send_messenger(row, message, dry_run)
                channels_results.append(result)
                if result.get("sent"):
                    record_sent_message(sm_id, msg_type, "messenger")

        # Always update SmartMoving note (not dry run)
        note_result = _update_smartmoving_note(row, live_followup, message, channels_results)
        if note_result.get("ok"):
            stats["note_updated"] += 1
            record_sent_message(sm_id, msg_type, "smartmoving_note")
            updated_jobs.append({
                "name": name,
                "smartmoving_id": sm_id,
                "note_id": str(note_id),
                "due_date_time": str(live_followup.get("dueDateTime") or ""),
                "dedup_key": msg_type,
            })
        else:
            stats["note_failed"] += 1
            failed_jobs.append({
                "name": name,
                "smartmoving_id": sm_id,
                "note_id": str(note_id),
                "error": note_result.get("error", "failed"),
                "dedup_key": msg_type,
            })

        stats["processed"] += 1
        results.append({
            "note_id": note_id,
            "name": name,
            "smartmoving_id": sm_id,
            "message_source": message_source,
            "message_preview": message,
            "channels": channels_results,
            "note_update": note_result,
        })

        logger.info(
            "Followup %s (%s): source=%s, note_update=%s",
            note_id, name, message_source,
            "ok" if note_result.get("ok") else note_result.get("error", "failed"),
        )
        record_outreach_event(
            lead_id=str(row.get("lead_id") or "") or None,
            company_id=str(row.get("company_id") or "") or None,
            smartmoving_id=sm_id,
            note_id=str(note_id),
            outreach_type="due",
            job_id=sm_id,
            qualified=qualified,
            qualification_reason="ok" if note_result.get("ok") else note_result.get("error", "note_update_failed"),
            message=message_preview,
            messenger=bool(row.get("facebook_user_id")),
            aircall=bool(row.get("phone")),
            dry_run=dry_run,
        )

    if updated_jobs:
        logger.info("Updated followups list (%d): %s", len(updated_jobs), updated_jobs)
    if failed_jobs:
        logger.info("Failed followups list (%d): %s", len(failed_jobs), failed_jobs)

    smartmoving_requests = get_request_counters()
    logger.info("SmartMoving request summary (followup_messages): %s", smartmoving_requests)

    return {"stats": stats, "results": results, "smartmoving_requests": smartmoving_requests}
