"""Run scheduled lead duplication through the CRM-owned copy workflow."""

import json
import logging
import os

import boto3
import httpx

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _get_admin_password() -> str:
    parameter = os.environ.get(
        "MOVING_CRM_ADMIN_PASSWORD_PARAM",
        "/meta-webhook/MOVINGCRM_ADMIN_PASSWORD",
    )
    ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    response = ssm.get_parameter(Name=parameter, WithDecryption=True)
    return response["Parameter"]["Value"]


def _login(api_url: str) -> str:
    email = os.getenv("MOVING_CRM_ADMIN_EMAIL", "admin@gorillamove.com")
    response = httpx.post(
        f"{api_url}/api/auth/login",
        json={"email": email, "password": _get_admin_password()},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["token"]


def _process(body: dict) -> dict:
    lead_id = body["lead_id"]
    target_company_name = body["target_company_name"]
    target_referral_source = body["target_referral_source"]
    api_url = os.getenv("API_URL", "").rstrip("/")
    if not api_url:
        raise RuntimeError("API_URL env var not set")

    token = _login(api_url)
    headers = {"Authorization": f"Bearer {token}"}
    lead_response = httpx.get(f"{api_url}/api/leads/{lead_id}", headers=headers, timeout=10)
    lead_response.raise_for_status()
    status = (lead_response.json().get("status") or "").strip().lower()
    if status in {"booked", "scheduled", "completed"}:
        return {"status": "skipped", "reason": status}
    if status in {"lost", "cancelled"} and not body.get("approved"):
        return {"status": "awaiting_approval"}

    # The Company Directory is the sole source of company configuration.
    companies_response = httpx.get(f"{api_url}/api/companies", headers=headers, timeout=10)
    companies_response.raise_for_status()
    matches = [
        company
        for company in companies_response.json()
        if company.get("name") == target_company_name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Target company was not found uniquely in Moving CRM: {target_company_name}"
        )

    # The backend reads the selected company's SmartMoving branch ID from the DB.
    copy_response = httpx.post(
        f"{api_url}/api/leads/{lead_id}/copy",
        json={
            "company_id": matches[0]["id"],
            "referral_source": target_referral_source,
        },
        headers=headers,
        timeout=40,
    )
    if not copy_response.is_success:
        raise RuntimeError(
            f"Moving CRM HTTP {copy_response.status_code}: {copy_response.text[:1000]}"
        )
    result = copy_response.json()
    logger.info("Duplicated lead %s to %s through Moving CRM", lead_id, target_company_name)
    return {
        "status": "created",
        "moving_crm": {
            "status_code": copy_response.status_code,
            "response": result,
        },
    }


def _record_result(body, error=None, awaiting_approval=False):
    """Keep failed schedules visible; remove them only after a confirmed copy."""
    name = body.get("schedule_name")
    if not name:
        return
    scheduler = boto3.client("scheduler")
    if error is None and not awaiting_approval:
        scheduler.delete_schedule(Name=name, GroupName="default")
        return
    schedule = scheduler.get_schedule(Name=name, GroupName="default")
    # UpdateSchedule replaces the configuration, so preserve the target and timing.
    settings = {key: schedule[key] for key in (
        "ScheduleExpression", "ScheduleExpressionTimezone", "StartDate", "EndDate",
        "State", "KmsKeyArn", "Target", "FlexibleTimeWindow",
    ) if key in schedule}
    settings["Target"] = {**settings["Target"], "Input": json.dumps(body)}
    if awaiting_approval:
        settings["State"] = "DISABLED"
    scheduler.update_schedule(
        Name=name, GroupName="default", **settings,
        ActionAfterCompletion="NONE",
        Description="Awaiting duplication approval" if awaiting_approval else ("Duplication failed: " + str(error))[:512],
    )


def _run(body):
    try:
        result = _process(body)
    except Exception as exc:
        try:
            _record_result(body, exc)
        except Exception:
            logger.exception("Could not save duplication failure on its schedule")
        raise
    try:
        _record_result(body, awaiting_approval=result.get("status") == "awaiting_approval")
    except Exception:
        # Do not retry a successful copy because schedule cleanup failed.
        logger.exception("Copy succeeded but its pending schedule could not be removed")
    return result


def handler(event, context):
    if not isinstance(event, dict) or "Records" not in event:
        logger.info("lead-duplicate handler invoked directly")
        return {"ok": True, "result": _run(event)}

    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            _run(json.loads(record["body"]))
        except Exception:
            logger.exception("Failed to process SQS record %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
