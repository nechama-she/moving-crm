"""Lead followup service — reads leads from CRM database, checks SmartMoving status, sends SMS."""

import logging
from datetime import datetime, timedelta

from config import SMS_MESSAGE_TEMPLATE, SMS_DAY3_TEMPLATE
from database import get_leads_for_followup
from libs.aircall import send_sms, find_number_id
from libs.smartmoving import get_opportunity

logger = logging.getLogger(__name__)


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


def run(days_back: int = 1, limit: int = 0) -> dict:
    """Main followup flow: read leads from DB, check SmartMoving status, send SMS.

    Time window: 6 PM (days_back+1 ago) → 6 PM (days_back ago).
    Example: days_back=1 on March 23 → March 21 18:00 to March 22 18:00.
    """
    today = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
    window_end = today - timedelta(days=days_back)
    window_start = window_end - timedelta(days=1)
    logger.info("Filter window: %s → %s", window_start, window_end)

    template = SMS_DAY3_TEMPLATE if days_back >= 2 else SMS_MESSAGE_TEMPLATE

    rows = get_leads_for_followup(window_start, window_end, limit=limit)

    stats = {"total": len(rows), "matched": 0, "errors": 0, "skipped": 0, "sms_sent": 0, "sms_failed": 0}
    results = []

    for row in rows:
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

        sms_result = None
        if _should_send_sms(lead_status, status_val):
            phone = str(row.get("phone", "")).strip()
            company_name = row.get("company_name", "")
            company_phone = row.get("company_phone", "")
            aircall_number_id = row.get("aircall_number_id")
            sms_result = _send_followup_sms(name, phone, company_name, company_phone, aircall_number_id, template=template)
            if sms_result["sent"]:
                stats["sms_sent"] += 1
            else:
                stats["sms_failed"] += 1

        results.append({
            "name": name,
            "email": row.get("email", ""),
            "phone": row.get("phone", ""),
            "opportunity_id": opp_id,
            "smartmoving_status": opp.get("status") or opp.get("opportunityStatus") or "",
            "lead_status": lead_status,
            "sms": sms_result,
        })

    return {"stats": stats, "results": results}
