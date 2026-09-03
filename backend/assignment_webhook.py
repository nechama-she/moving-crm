"""Meta-webhook notification for completed salesperson assignments."""

import logging
import os
from typing import Any

import httpx

from libs.common.ssm import get_ssm_cached
from models import Lead, User

logger = logging.getLogger("moving-crm")


def send_assignment_webhook(lead: Lead, rep: User | None) -> dict[str, Any]:
    if not rep:
        return {"attempted": False, "ok": False, "error": "No rep was assigned"}

    opportunity_id = str(lead.smartmoving_id or "").strip()
    if not opportunity_id:
        return {"attempted": False, "ok": False, "error": "Lead does not have a SmartMoving ID"}

    ssm_prefix = os.getenv("SSM_PREFIX", "/moving-crm/dev/").rstrip("/")
    webhook_url = get_ssm_cached(f"{ssm_prefix}/META_WEBHOOK_URL").strip()
    if not webhook_url:
        return {"attempted": False, "ok": False, "error": "META_WEBHOOK_URL is not configured"}

    payload = {
        "event-type": "sales-person-changed",
        "opportunity-id": opportunity_id,
        "rep-name": str(rep.name or "").strip(),
    }
    try:
        response = httpx.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json", "User-Agent": "moving-crm"},
            timeout=10.0,
        )
        response_body = response.text[:1500]
        if not 200 <= response.status_code < 300:
            logger.warning(
                "Meta assignment webhook rejected opportunity=%s rep=%s status=%s body=%s",
                opportunity_id,
                rep.id,
                response.status_code,
                response_body,
            )
            return {
                "attempted": True,
                "ok": False,
                "status": response.status_code,
                "error": f"HTTP {response.status_code}: {response_body or 'empty response'}",
            }
        logger.info(
            "Meta assignment webhook sent opportunity=%s rep=%s status=%s",
            opportunity_id,
            rep.id,
            response.status_code,
        )
        return {"attempted": True, "ok": True, "status": response.status_code}
    except httpx.RequestError as exc:
        logger.warning(
            "Meta assignment webhook failed opportunity=%s rep=%s error=%s",
            opportunity_id,
            rep.id,
            exc,
        )
        return {"attempted": True, "ok": False, "error": str(exc)}
