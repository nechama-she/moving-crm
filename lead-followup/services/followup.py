"""Lead followup service — reads leads from CRM database, checks SmartMoving status, sends SMS."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import SMS_MESSAGE_TEMPLATE, SMS_DAY3_TEMPLATE
from database import get_leads_for_followup, was_already_sent, record_sent_message
from libs.aircall import send_sms, find_number_id
from libs.smartmoving import get_opportunity

logger = logging.getLogger(__name__)


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


def _send_followup_sms(name: str, phone: str, company_name: str, company_phone: str, aircall_number_id: str | None, template: str = None) -> dict:
    """Send a followup SMS to a lead. Returns result dict."""
    if not phone:
        return {"sent": False, "error": "no_phone_number"}

    msg_text = (template or SMS_MESSAGE_TEMPLATE).format(name=name, company=company_name)

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
        stats["matched"] += 1

        qualifies = _should_send_sms(lead_status, status_val)
        sms_result = None
        if qualifies:
            phone = str(row.get("phone", "")).strip()
            company_name = row.get("company_name", "")
            company_phone = row.get("company_phone", "")
            aircall_number_id = row.get("aircall_number_id")
            day_label = f"day_{days_back + 1}"  # days_back=1 → day_2, days_back=2 → day_3

            # Dedup: skip if already sent for this lead + day
            if was_already_sent(opp_id, day_label, "aircall"):
                logger.info("SKIP %s (%s): %s already sent", name, opp_id, day_label)
                sms_result = {"sent": False, "skipped": True, "reason": "already_sent"}
            elif dry_run:
                msg_text = (template or SMS_MESSAGE_TEMPLATE).format(name=name, company=company_name)
                sms_result = {"sent": False, "dry_run": True, "would_send_to": phone, "message": msg_text}
                logger.info("DRY RUN — would send to %s: %s", phone, msg_text)
            else:
                sms_result = _send_followup_sms(name, phone, company_name, company_phone, aircall_number_id, template=template)
                if sms_result.get("sent"):
                    record_sent_message(opp_id, day_label, "aircall")
            if sms_result.get("sent"):
                stats["sms_sent"] += 1
            elif not sms_result.get("dry_run"):
                stats["sms_failed"] += 1

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

    return {"stats": stats, "results": results, "windows": windows}
