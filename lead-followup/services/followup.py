"""Lead followup service — reads leads from CRM database, checks SmartMoving status, sends SMS."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import SMS_MESSAGE_TEMPLATE, SMS_DAY3_TEMPLATE
from database import get_leads_for_followup, was_already_sent, record_sent_message, get_sales_rep_number, get_sales_rep_info, record_outreach_event
from libs.aircall import send_sms, find_number_id
from libs.common.phone import phone_variants
from libs.smartmoving import get_opportunity, add_opportunity_note, reset_request_counters, get_request_counters

logger = logging.getLogger(__name__)


def _is_client_message(item: dict) -> bool:
    direction = str(item.get("direction") or "").strip().lower()
    if direction in {"received", "incoming", "inbound", "from_client"}:
        return True
    if direction in {"sent", "outgoing", "outbound", "from_company"}:
        return False

    if bool(item.get("is_outbound")) or bool(item.get("from_me")):
        return False

    sender_type = str(item.get("sender_type") or item.get("sender") or "").strip().lower()
    if sender_type in {"client", "customer", "lead", "user"}:
        return True
    if sender_type in {"agent", "company", "rep", "system", "page"}:
        return False

    return False


def _has_client_messages(phone: str, facebook_user_id: str) -> bool:
    """Best-effort inbound message check from SMS/Messenger history."""
    try:
        import boto3
        from boto3.dynamodb.conditions import Key, Attr
    except Exception:
        logger.warning("boto3 not available; skipping client-message check")
        return False

    region = "us-east-1"
    try:
        dynamodb = boto3.resource("dynamodb", region_name=region)

        if phone:
            sms_table = dynamodb.Table("sms_messages")
            for variant in phone_variants(phone):
                try:
                    resp = sms_table.query(
                        KeyConditionExpression=Key("phone_number").eq(variant),
                        ScanIndexForward=False,
                        Limit=30,
                    )
                    for item in resp.get("Items", []):
                        if _is_client_message(item):
                            return True
                except Exception:
                    continue

        if facebook_user_id:
            conv_table = dynamodb.Table("conversations")
            try:
                resp = conv_table.query(
                    KeyConditionExpression=Key("user_id").eq(facebook_user_id),
                    FilterExpression=Attr("platform").eq("messenger"),
                    ScanIndexForward=False,
                    Limit=50,
                )
                for item in resp.get("Items", []):
                    if _is_client_message(item):
                        return True
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Non-fatal client message check failure: %s", exc)

    return False


def compute_utc_window(timezone_str: str, days_back: int = 1) -> tuple:
    """Convert 6 PM in a local timezone to a UTC start/end window.

    Returns (window_start_utc, window_end_utc) as naive datetimes.
    """
    tz = ZoneInfo(timezone_str or "America/New_York")
    now_local = datetime.now(tz)
    today_6pm = now_local.replace(hour=18, minute=0, second=0, microsecond=0)
    window_end = today_6pm - timedelta(days=days_back)
    window_start = window_end - timedelta(days=1)
    ws_utc = window_start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    we_utc = window_end.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return ws_utc, we_utc


def _should_send_sms(lead_status: str, status_val) -> bool:
    """Determine if a lead qualifies for SMS outreach."""
    return (lead_status == "Priority 0" or not lead_status) and status_val in (0, 1, 3)


def _render_followup_message(name: str, company_name: str, template: str | None = None) -> str:
    return (template or SMS_MESSAGE_TEMPLATE).format(name=name, company=company_name)


def _build_company_signature(company_name: str, company_phone: str) -> str:
    """Build company fallback signature."""
    parts = ["Thanks,"]
    if company_name:
        parts[-1] = f"Thanks, {company_name}"
    if company_phone:
        parts.append(company_phone)
    return "\n".join(parts)


def _build_signature(company_name: str, company_phone: str, opportunity: dict | None = None) -> str:
    """Build signature: use rep if available, otherwise company."""
    sales_assignee = (opportunity or {}).get("salesAssignee") or {}
    rep_name = (sales_assignee.get("name") or "").strip()
    if rep_name:
        rep_info = get_sales_rep_info(rep_name)
        if rep_info and rep_info.get("phone"):
            return f"Thanks, {rep_info['name']}\n{rep_info['phone']}"
        elif rep_info:
            logger.info("Sales rep %s is in users table but phone is missing; using company signature", rep_name)
    return _build_company_signature(company_name, company_phone)


def _send_followup_sms(name: str, phone: str, company_name: str, company_phone: str, aircall_number_id: str | None, template: str = None, signature: str = "") -> dict:
    """Send a followup SMS to a lead. Returns result dict."""
    if not phone:
        return {"sent": False, "error": "no_phone_number"}

    msg_text = _render_followup_message(name, company_name, template=template)
    if signature:
        msg_text = f"{msg_text}\n\n{signature}"

    # Use stored aircall_number_id, or find it from company phone
    nid = aircall_number_id
    if not nid and company_phone:
        nid = find_number_id(company_phone)

    sms_resp = send_sms(to=phone, text=msg_text, number_id=nid)

    if sms_resp["ok"]:
        return {"sent": True, "message_id": sms_resp["message_id"], "to": sms_resp.get("to"), "from": company_phone}
    return {"sent": False, "error": sms_resp.get("error"), "detail": sms_resp.get("detail")}


def run(days_back: int = 1, limit: int = 0, dry_run: bool = False) -> dict:
    """Main followup flow: read leads from DB, check SmartMoving status, send SMS.

    Time window: 6 PM–6 PM in each company's timezone (from DB).
    If dry_run=True, skips actual SMS send but logs everything else.
    """
    if dry_run:
        logger.info("*** DRY RUN — SMS will NOT be sent ***")
    reset_request_counters()
    # First, get all companies' timezones to compute the right UTC windows
    from database import get_company_timezones
    companies = get_company_timezones()

    all_rows = []
    windows = []
    for company in companies:
        ws_utc, we_utc = compute_utc_window(company["timezone"], days_back)
        tz_name = company["timezone"] or "America/New_York"
        tz = ZoneInfo(tz_name)
        ws_local = ws_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).strftime("%Y-%m-%d %H:%M")
        we_local = we_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).strftime("%Y-%m-%d %H:%M")
        logger.info("Company %s (tz=%s): %s → %s UTC (%s → %s local)", company["name"], tz_name, ws_utc, we_utc, ws_local, we_local)
        windows.append({"company": company["name"], "timezone": tz_name, "window_start": str(ws_utc), "window_end": str(we_utc), "local_start": ws_local, "local_end": we_local})
        rows = get_leads_for_followup(ws_utc, we_utc, limit=limit, company_id=company["id"])
        all_rows.extend(rows)

    logger.info("Total leads across all companies: %d", len(all_rows))

    template = SMS_DAY3_TEMPLATE if days_back >= 2 else SMS_MESSAGE_TEMPLATE

    stats = {"total": len(all_rows), "matched": 0, "errors": 0, "skipped": 0, "sms_sent": 0, "sms_failed": 0}
    results = []

    for row in all_rows:
        name = row.get("full_name", "").strip()
        opp_id = row.get("smartmoving_id", "").strip()

        if not opp_id:
            stats["skipped"] += 1
            results.append({"name": name, "result": "skipped_no_id"})
            continue

        opp_resp = get_opportunity(opp_id)
        if "error" in opp_resp:
            stats["errors"] += 1
            results.append({"name": name, "opportunity_id": opp_id, "result": "error", "error": opp_resp["error"]})
            continue

        opp = opp_resp["data"]
        lead_status = opp.get("leadStatus", "")
        status_val = opp.get("status")
        try:
            status_reason_val = int(status_val) if status_val is not None else "unknown"
        except (TypeError, ValueError):
            status_reason_val = str(status_val or "unknown")
        stats["matched"] += 1

        phone = str(row.get("phone", "")).strip()
        facebook_user_id = str(row.get("facebook_user_id", "") or "").strip()
        has_client_contact = _has_client_messages(phone=phone, facebook_user_id=facebook_user_id)

        qualifies = _should_send_sms(lead_status, status_val)
        sms_result = None
        qualification_reason = "ok" if qualifies else f"status_{status_reason_val}_not_allowed"

        if has_client_contact:
            qualifies = False
            qualification_reason = "client_already_contacted"

            # If SmartMoving status is 0 and client has already contacted us, leave a note for the rep.
            if status_val == 0:
                note_text = "CRM note: client already made contact. Day 2/3 auto-followup was skipped. SmartMoving status should be changed."
                note_resp = add_opportunity_note(opp_id, note_text)
                if not note_resp.get("ok"):
                    logger.warning("Failed to add SmartMoving note for %s: %s", opp_id, note_resp.get("error"))

        preview_message = _render_followup_message(name, row.get("company_name", ""), template=template) if qualifies else ""
        if qualifies:
            company_name = row.get("company_name", "")
            company_phone = row.get("company_phone", "")
            aircall_number_id = row.get("aircall_number_id")
            day_label = f"day_{days_back + 1}"  # days_back=1 → day_2, days_back=2 → day_3

            # Use sales rep's Aircall number if they have one, otherwise company fallback
            sales_assignee = opp.get("salesAssignee") or {}
            rep_name = (sales_assignee.get("name") or "").strip()
            rep_number = get_sales_rep_number(rep_name) if rep_name else None
            if rep_number:
                logger.info("Using sales rep %s Aircall number %s", rep_name, rep_number)
                aircall_number_id = rep_number

            # Build signature: rep if available, otherwise company
            signature = _build_signature(company_name, company_phone, opportunity=opp)

            # Dedup: skip if already sent for this lead + day
            if was_already_sent(opp_id, day_label, "aircall"):
                logger.info("SKIP %s (%s): %s already sent", name, opp_id, day_label)
                sms_result = {"sent": False, "skipped": True, "reason": "already_sent"}
                qualification_reason = "already_sent"
            elif dry_run:
                msg_text = _render_followup_message(name, company_name, template=template)
                if signature:
                    msg_text = f"{msg_text}\n\n{signature}"
                sms_result = {"sent": False, "dry_run": True, "would_send_to": phone, "message": msg_text}
                logger.info("DRY RUN — would send to %s: %s", phone, msg_text)
            else:
                sms_result = _send_followup_sms(name, phone, company_name, company_phone, aircall_number_id, template=template, signature=signature)
                if sms_result.get("sent"):
                    record_sent_message(opp_id, day_label, "aircall")
                elif sms_result.get("error"):
                    qualification_reason = sms_result.get("error") or "send_failed"
            if sms_result.get("sent"):
                stats["sms_sent"] += 1
            elif not sms_result.get("dry_run"):
                stats["sms_failed"] += 1

        record_outreach_event(
            lead_id=str(row.get("id") or "") or None,
            company_id=str(row.get("company_id") or "") or None,
            smartmoving_id=opp_id or None,
            note_id=None,
            outreach_type=f"day_{days_back + 1}",
            job_id=opp_id or None,
            qualified=qualifies,
            qualification_reason=qualification_reason,
            message=(sms_result or {}).get("message") or preview_message,
            messenger=False,
            aircall=bool(row.get("phone")),
            dry_run=bool((sms_result or {}).get("dry_run", dry_run)),
        )

        results.append({
            "name": name,
            "email": row.get("email", ""),
            "phone": row.get("phone", ""),
            "created_at": row.get("created_at", ""),
            "company_timezone": row.get("company_timezone", ""),
            "opportunity_id": opp_id,
            "smartmoving_status": opp.get("status") or opp.get("opportunityStatus") or "",
            "lead_status": lead_status,
            "qualifies": qualifies,
            "sms": sms_result,
        })

    smartmoving_requests = get_request_counters()
    logger.info("SmartMoving request summary (day_followup): %s", smartmoving_requests)

    return {"stats": stats, "results": results, "windows": windows, "smartmoving_requests": smartmoving_requests}
