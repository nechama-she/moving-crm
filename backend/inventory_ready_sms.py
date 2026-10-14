"""Inventory completion SMS is disabled in every environment."""
import json
import logging
from datetime import datetime

from models import Company, Lead, LeadLiveSwitch, PublicMoveAccess

logger = logging.getLogger(__name__)


def production_sms_enabled():
    # Customer-requested global disable, including production.
    return False


def notify_inventory_ready(lead_id, report_id, db):
    # Fail closed before loading customers or calling any messaging provider.
    if not production_sms_enabled():
        return
    from libs.aircall.client import find_number_id, send_sms
    from routes.public_moves import public_url

    saved = db.query(LeadLiveSwitch).filter_by(lead_id=lead_id).populate_existing().with_for_update().first()
    state = json.loads(saved.details or "{}") if saved else {}
    if (not report_id or state.get("last_spark_id") != report_id
            or state.get("spark_extracted_id") != report_id
            or state.get("last_spark_status") != "completed"
            or state.get("report_source") == "manual"
            or not any((row.get("content_type") or "").lower().startswith("video/")
                       for row in state.get("report_files", []))):
        return
    notices = state.get("inventory_ready_sms", {})
    if report_id in notices:
        return
    lead = db.get(Lead, lead_id)
    access = db.query(PublicMoveAccess).filter(
        PublicMoveAccess.lead_id == lead_id, PublicMoveAccess.revoked.is_(False),
        PublicMoveAccess.expires_at > datetime.utcnow(),
    ).order_by(PublicMoveAccess.created_at.desc()).first()
    if not lead or not lead.phone or not access:
        return
    company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    number = company.aircall_number_id if company else None
    if not number and company and company.phone:
        number = find_number_id(company.phone)
    if not number:
        return
    url = public_url(access)
    # Persist a claim before the external call. An ambiguous provider timeout
    # must not lead to a second customer text on a repeated completion callback.
    notices[report_id] = {"status": "attempted", "at": datetime.utcnow().isoformat()}
    state["inventory_ready_sms"] = notices
    saved.details = json.dumps(state)
    db.commit()
    result = send_sms(to=lead.phone, text=f"Your inventory is ready! View it on your customer page: {url}",
                      number_id=number, sensitive=True)
    db.refresh(saved, with_for_update=True)
    state = json.loads(saved.details or "{}")
    state.setdefault("inventory_ready_sms", {})[report_id] = {
        **notices[report_id], "status": "sent" if result.get("ok") else "failed",
    }
    saved.details = json.dumps(state)
    db.commit()


def try_notify_inventory_ready(lead_id, report_id, db):
    try:
        notify_inventory_ready(lead_id, report_id, db)
    except Exception:
        db.rollback()
        # Do not expose phone numbers or signed customer links in logs.
        logger.warning("Inventory completion SMS failed for report %s", report_id)
