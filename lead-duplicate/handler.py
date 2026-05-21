"""Lambda entry point — lead duplication.

Triggered by SQS after a 10-minute message delay. Fetches the source lead
from the CRM API and re-submits it under the target company via POST /api/leads.

Expected SQS message body (JSON):
    {
        "lead_id":           "<uuid>",
        "source_company_id": "<uuid>",
        "target_company_id": "<uuid>"
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
    target_company_id = body["target_company_id"]

    api_url = os.getenv("API_URL", "").rstrip("/")
    if not api_url:
        raise RuntimeError("API_URL env var not set")

    api_secret = _get_api_secret()

    # ── Fetch source lead via API ───────────────────────────────────────────
    get_resp = httpx.get(
        f"{api_url}/api/leads/{lead_id}",
        headers={"x-api-secret": api_secret},
        timeout=10,
    )
    if get_resp.status_code == 404:
        logger.warning("Source lead %s not found; skipping", lead_id)
        return
    get_resp.raise_for_status()
    lead = get_resp.json()

    # ── Resolve target company name ─────────────────────────────────────────
    companies_resp = httpx.get(
        f"{api_url}/api/companies",
        headers={"x-api-secret": api_secret},
        timeout=10,
    )
    companies_resp.raise_for_status()
    companies = {c["id"]: c["name"] for c in companies_resp.json()}

    target_company_name = companies.get(target_company_id)
    if not target_company_name:
        raise ValueError(f"Target company {target_company_id} not found")

    # ── Submit duplicate lead ───────────────────────────────────────────────
    payload = {
        "full_name":       lead.get("full_name", ""),
        "email":           lead.get("email", ""),
        "phone_number":    lead.get("phone_number", ""),
        "pickup_zip":      lead.get("pickup_zip", ""),
        "delivery_zip":    lead.get("delivery_zip", ""),
        "move_size":       lead.get("move_size", ""),
        "move_date":       lead.get("when_is_the_move?", ""),
        "move_type":       lead.get("are_you_moving_within_the_state_or_out_of_state?", ""),
        "created_time":    lead.get("created_time", ""),
        "leadgen_id":      lead.get("leadgen_id", ""),
        "smartmoving_id":  "",  # clean slate — new company, new SmartMoving job
        "facebook_user_id": lead.get("user_id", ""),
        "notes":           lead.get("notes", ""),
        "referral_source": lead.get("referral_source", ""),
        "service_type":    lead.get("service_type", ""),
        "company_name":    target_company_name,
        "source":          lead.get("source", "zapier"),
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
            lead_id, target_company_id, result.get("reason"),
        )
        return

    logger.info(
        "Duplicated lead %s → new lead %s at company %s",
        lead_id, result.get("lead_id"), target_company_id,
    )


import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from database import get_engine

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
            # Report as batch item failure so only this message goes to DLQ
            failures.append({"itemIdentifier": message_id})

    if failures:
        return {"batchItemFailures": failures}


def _process(body: dict) -> None:
    lead_id = body["lead_id"]
    source_company_id = body["source_company_id"]
    target_company_id = body["target_company_id"]

    logger.info(
        "Duplicating lead %s from company %s to company %s",
        lead_id,
        source_company_id,
        target_company_id,
    )

    engine = get_engine()

    with engine.connect() as conn:
        # ── Fetch source lead ───────────────────────────────────────────────
        row = conn.execute(
            text("SELECT * FROM leads WHERE id = :id"),
            {"id": lead_id},
        ).mappings().first()

        if not row:
            logger.warning("Source lead %s not found; skipping", lead_id)
            return

        # ── Idempotency check ───────────────────────────────────────────────
        # Prefer leadgen_id for exact dedup; fall back to phone + company
        if row["leadgen_id"]:
            existing = conn.execute(
                text(
                    "SELECT id FROM leads"
                    " WHERE company_id = :company_id AND leadgen_id = :leadgen_id"
                    " LIMIT 1"
                ),
                {"company_id": target_company_id, "leadgen_id": row["leadgen_id"]},
            ).first()
        else:
            existing = conn.execute(
                text(
                    "SELECT id FROM leads"
                    " WHERE company_id = :company_id AND phone = :phone AND full_name = :full_name"
                    " LIMIT 1"
                ),
                {
                    "company_id": target_company_id,
                    "phone": row["phone"],
                    "full_name": row["full_name"],
                },
            ).first()

        if existing:
            logger.info(
                "Lead %s already duplicated to company %s (existing lead %s); skipping",
                lead_id,
                target_company_id,
                existing[0],
            )
            return

        # ── Insert duplicate ────────────────────────────────────────────────
        new_id = str(uuid.uuid4())
        now = _utcnow()

        conn.execute(
            text(
                """
                INSERT INTO leads (
                    id, company_id, assigned_to,
                    full_name, email, phone, source,
                    leadgen_id, smartmoving_id, facebook_user_id,
                    inbox_url, notes,
                    pickup_zip, delivery_zip, move_size, move_date, move_type,
                    service_type, referral_source, created_time,
                    status, priority, created_at, updated_at
                ) VALUES (
                    :id, :company_id, NULL,
                    :full_name, :email, :phone, :source,
                    :leadgen_id, NULL, :facebook_user_id,
                    :inbox_url, :notes,
                    :pickup_zip, :delivery_zip, :move_size, :move_date, :move_type,
                    :service_type, :referral_source, :created_time,
                    'new', :priority, :created_at, :updated_at
                )
                """
            ),
            {
                "id": new_id,
                "company_id": target_company_id,
                "full_name": row["full_name"],
                "email": row["email"],
                "phone": row["phone"],
                "source": row["source"],
                "leadgen_id": row["leadgen_id"],
                "facebook_user_id": row["facebook_user_id"],
                "inbox_url": row["inbox_url"],
                "notes": row["notes"],
                "pickup_zip": row["pickup_zip"],
                "delivery_zip": row["delivery_zip"],
                "move_size": row["move_size"],
                "move_date": row["move_date"],
                "move_type": row["move_type"],
                "service_type": row["service_type"],
                "referral_source": row["referral_source"],
                "created_time": row["created_time"],
                "priority": row["priority"] or 0,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()

    logger.info(
        "Duplicated lead %s → new lead %s under company %s",
        lead_id,
        new_id,
        target_company_id,
    )
