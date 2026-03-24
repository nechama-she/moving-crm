"""Lead followup service — orchestrates sheet reading, status checks, and SMS outreach."""

import json
import logging
from datetime import datetime, timedelta

from config import SMS_MESSAGE_TEMPLATE
from libs.aircall import send_sms
from libs.google_sheets import read_sheet
from libs.smartmoving import get_opportunity

logger = logging.getLogger(__name__)


def parse_lead_id(raw: str) -> str | None:
    """Extract the opportunity ID from the lead_id column (JSON or plain UUID)."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed.get("leadId") or parsed.get("lead_id") or parsed.get("id")
    except (json.JSONDecodeError, TypeError):
        pass
    if len(raw) == 36 and raw.count("-") == 4:
        return raw
    return None


def parse_datetime(val: str) -> datetime | None:
    """Parse created_time string into a datetime. Handles multiple sheet formats."""
    val = val.strip()
    if not val:
        return None
    for fmt in ("%m/%d/%y %I:%M %p", "%m/%d/%Y %I:%M %p", "%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _should_send_sms(lead_status: str, status_val) -> bool:
    """Determine if a lead qualifies for SMS outreach."""
    return (lead_status == "Priority 0" or not lead_status) and status_val in (0, 1, 3)


def _send_followup_sms(name: str, phone: str, branch: dict) -> dict:
    """Send a followup SMS to a lead. Returns result dict."""
    if not phone:
        return {"sent": False, "error": "no_phone_number"}

    branch_phone = branch.get("phoneNumber", "")
    branch_name = branch.get("name", "")
    msg_text = SMS_MESSAGE_TEMPLATE.format(name=name, company=branch_name)
    sms_resp = send_sms(to=phone, text=msg_text, from_phone=branch_phone)

    if sms_resp["ok"]:
        return {"sent": True, "message_id": sms_resp["message_id"], "to": sms_resp.get("to"), "from": branch_phone}
    return {"sent": False, "error": sms_resp.get("error"), "detail": sms_resp.get("detail")}


def run(days_back: int = 1, limit: int = 0) -> dict:
    """Main followup flow: read leads, check status, send SMS.

    Time window: 6 PM (days_back+1 ago) → 6 PM (days_back ago).
    Example: days_back=1 on March 23 → March 21 18:00 to March 22 18:00.
    """
    all_rows = read_sheet()

    today = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
    window_end = today - timedelta(days=days_back)
    window_start = window_end - timedelta(days=1)
    logger.info("Filter window: %s → %s", window_start, window_end)

    rows = []
    for row in all_rows:
        created = str(row.get("created_time", "")).strip()
        dt = parse_datetime(created)
        if dt and window_start <= dt < window_end:
            rows.append(row)

    if limit:
        rows = rows[:limit]

    stats = {"total": len(rows), "matched": 0, "errors": 0, "skipped": 0, "sms_sent": 0, "sms_failed": 0}
    results = []

    for row in rows:
        name = row.get("name", "").strip()
        lead_id_raw = row.get("lead_id", "").strip()
        opp_id = parse_lead_id(lead_id_raw)

        if not opp_id:
            stats["skipped"] += 1
            results.append({"name": name, "result": "skipped_no_id", "raw_lead_id": lead_id_raw})
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
            phone = str(row.get("phone_number", "")).strip()
            branch = opp.get("branch", {})
            sms_result = _send_followup_sms(name, phone, branch)
            if sms_result["sent"]:
                stats["sms_sent"] += 1
            else:
                stats["sms_failed"] += 1

        results.append({
            "name": name,
            "email": row.get("email", ""),
            "phone": row.get("phone_number", ""),
            "opportunity_id": opp_id,
            "smartmoving_status": opp.get("status") or opp.get("opportunityStatus") or "",
            "lead_status": lead_status,
            "sms": sms_result,
            "opportunity_data": opp,
        })

    return {"stats": stats, "results": results}
