"""Lambda entry point — lead duplication.

Triggered by SQS after a 10-minute message delay. Fetches the source lead
from the CRM API and re-submits it under the target company via POST /api/leads.

Expected SQS message body (JSON):
    {
        "lead_id":                "<uuid>",
        "target_company_name":    "Top Tier Van Lines",
        "target_referral_source": "Facebook-TTVL-HHG-Nationwide"
    }
"""

import json
import logging
import os

import boto3
import httpx

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _get_api_secret() -> str:
    ssm_prefix = os.getenv("SSM_PREFIX", "/moving-crm/dev/")
    key = ssm_prefix.rstrip("/") + "/API_SECRET"
    ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    resp = ssm.get_parameter(Name=key, WithDecryption=True)
    return resp["Parameter"]["Value"]


def _get_admin_password() -> str:
    ssm_prefix = os.getenv("SSM_PREFIX", "/moving-crm/dev/")
    param = ssm_prefix.rstrip("/") + "/ADMIN_PASSWORD"
    logger.info("Fetching admin password from SSM: %s", param)
    ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    resp = ssm.get_parameter(Name=param, WithDecryption=True)
    password = resp["Parameter"]["Value"]
    logger.info("Admin password retrieved: length=%d preview=%s...%s", len(password), password[:3], password[-3:])
    return password


def _login(api_url: str) -> str:
    email = os.getenv("MOVING_CRM_ADMIN_EMAIL", "admin@gorillamove.com")
    password = _get_admin_password()
    logger.info("Logging in as %s to %s/api/auth/login", email, api_url)
    resp = httpx.post(
        f"{api_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    logger.info("Login response: status=%d body=%s", resp.status_code, resp.text[:300])
    resp.raise_for_status()
    return resp.json()["token"]


def handler(event, context):
    records = event.get("Records", [])
    logger.info("lead-duplicate handler invoked with %d record(s)", len(records))

    failures = []
    for record in records:
        message_id = record.get("messageId", "unknown")
        try:
            body = json.loads(record["body"])
            _process(body)
        except Exception:
            logger.exception("Failed to process SQS record %s", message_id)
            failures.append({"itemIdentifier": message_id})

    if failures:
        return {"batchItemFailures": failures}


def _process(body: dict) -> None:
    lead_id = body["lead_id"]
    target_company_name = body["target_company_name"]
    target_referral_source = body["target_referral_source"]
    logger.info("Processing lead_id=%s target_company=%s target_referral=%s", lead_id, target_company_name, target_referral_source)

    api_url = os.getenv("API_URL", "").rstrip("/")
    logger.info("API_URL=%s SSM_PREFIX=%s", api_url, os.getenv("SSM_PREFIX", "NOT SET"))
    if not api_url:
        raise RuntimeError("API_URL env var not set")

    api_secret = _get_api_secret()
    token = _login(api_url)

    # ── Fetch source lead via API ───────────────────────────────────────────
    get_url = f"{api_url}/api/leads/{lead_id}"
    logger.info("GET %s", get_url)
    get_resp = httpx.get(
        get_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    logger.info("GET %s → status=%d body=%s", get_url, get_resp.status_code, get_resp.text[:300])
    if get_resp.status_code == 404:
        logger.warning("Source lead %s not found; skipping", lead_id)
        return
    get_resp.raise_for_status()
    lead = get_resp.json()

    # ── Submit duplicate lead ───────────────────────────────────────────────
    payload = {
        "full_name":        lead.get("full_name", ""),
        "email":            lead.get("email", ""),
        "phone_number":     lead.get("phone_number", ""),
        "pickup_zip":       lead.get("pickup_zip", ""),
        "delivery_zip":     lead.get("delivery_zip", ""),
        "move_size":        lead.get("move_size", ""),
        "move_date":        lead.get("when_is_the_move?", ""),
        "move_type":        lead.get("are_you_moving_within_the_state_or_out_of_state?", ""),
        "created_time":     lead.get("created_time", ""),
        "leadgen_id":       lead.get("leadgen_id", ""),
        "smartmoving_id":   "",
        "facebook_user_id": lead.get("user_id", ""),
        "notes":            lead.get("notes", ""),
        "referral_source":  target_referral_source,
        "service_type":     lead.get("service_type", ""),
        "company_name":     target_company_name,
        "source":           lead.get("source", "zapier"),
    }

    post_resp = httpx.post(
        f"{api_url}/api/leads",
        json=payload,
        headers={"x-api-secret": api_secret},
        timeout=15,
    )
    post_resp.raise_for_status()
    result = post_resp.json()

    if result.get("status") == "skipped":
        logger.info(
            "Lead %s already exists at company %s (reason=%s); skipping",
            lead_id, target_company_name, result.get("reason"),
        )
        return

    logger.info(
        "Duplicated lead %s → new lead %s at company %s",
        lead_id, result.get("lead_id"), target_company_name,
    )

