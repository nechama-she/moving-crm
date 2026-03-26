"""Aircall API client — phone number resolution and SMS sending."""

import base64
import logging
import os
import re
from functools import lru_cache

import boto3
import httpx
from botocore.exceptions import ClientError

AIRCALL_BASE_URL = os.getenv("AIRCALL_BASE_URL", "https://api.aircall.io/v1")
AIRCALL_LAMBDA_SOURCE = os.getenv("AIRCALL_LAMBDA_SOURCE", "meta_webhook")

logger = logging.getLogger(__name__)


@lru_cache()
def _get_creds() -> tuple[str, str, str]:
    """Read Aircall creds from env vars, SSM, or meta_webhook Lambda."""
    api_id = os.getenv("AIRCALL_API_ID", "")
    api_token = os.getenv("AIRCALL_API_TOKEN", "")
    number_id = os.getenv("AIRCALL_NUMBER_ID", "")

    # Try SSM — first app-specific prefix, then /meta-webhook/
    if not api_id or not api_token:
        try:
            from config import get_config
            cfg = get_config()
            api_id = api_id or cfg.get("AIRCALL_API_ID", "")
            api_token = api_token or cfg.get("AIRCALL_API_TOKEN", "")
            number_id = number_id or cfg.get("AIRCALL_NUMBER_ID", "")
        except (ImportError, Exception):
            pass

    if not api_id or not api_token:
        try:
            ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
            resp = ssm.get_parameters_by_path(Path="/meta-webhook/", WithDecryption=True)
            params = {p["Name"].split("/")[-1]: p["Value"] for p in resp.get("Parameters", [])}
            api_id = api_id or params.get("AIRCALL_API_ID", "")
            api_token = api_token or params.get("AIRCALL_API_TOKEN", "")
            number_id = number_id or params.get("AIRCALL_NUMBER_ID", "")
            logger.info("Loaded Aircall creds from SSM /meta-webhook/")
        except ClientError as e:
            logger.warning("Could not read Aircall creds from SSM: %s", e)

    return api_id, api_token, number_id


def _auth_header() -> str:
    api_id, api_token, _ = _get_creds()
    creds = base64.b64encode(f"{api_id}:{api_token}".encode()).decode()
    return f"Basic {creds}"


def _digits(phone: str) -> str:
    """Strip a phone string to digits only."""
    return re.sub(r"\D", "", phone)


def _to_e164(phone: str) -> str:
    """Normalize a US phone number to E.164 format (+1XXXXXXXXXX)."""
    digits = _digits(phone)
    if len(digits) == 10:
        digits = "1" + digits
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits


@lru_cache()
def get_numbers() -> list[dict]:
    """Fetch all Aircall numbers (cached for the Lambda invocation lifetime)."""
    headers = {"Authorization": _auth_header()}
    try:
        resp = httpx.get(f"{AIRCALL_BASE_URL}/numbers", headers=headers, timeout=15)
        resp.raise_for_status()
        numbers = resp.json().get("numbers", [])
        logger.info("Loaded %d Aircall numbers", len(numbers))
        return numbers
    except Exception as e:
        logger.error("Failed to fetch Aircall numbers: %r", e)
        return []


@lru_cache()
def find_number_id(phone: str) -> str | None:
    """Find the Aircall number_id whose digits match the given phone string."""
    target = _digits(phone)
    if not target:
        return None
    for num in get_numbers():
        num_digits = _digits(str(num.get("digits", "")))
        if num_digits == target or num_digits.endswith(target) or target.endswith(num_digits):
            return str(num["id"])
    return None


def send_sms(to: str, text: str, number_id: str | None = None, from_phone: str | None = None) -> dict:
    """Send an SMS via Aircall.

    Returns {"ok": True, "message_id": ...} or {"ok": False, "error": ..., "detail": ...}.
    """
    nid = number_id
    if not nid and from_phone:
        nid = find_number_id(from_phone)
    if not nid:
        _, _, nid = _get_creds()
    if not nid:
        logger.error("Could not determine Aircall number to send from")
        return {"ok": False, "error": "no_aircall_number_found", "detail": f"Could not match from_phone={from_phone}"}

    to_formatted = _to_e164(str(to))
    url = f"{AIRCALL_BASE_URL}/numbers/{nid}/messages/native/send"
    headers = {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
    }
    body = {"to": to_formatted, "body": text}

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        msg_id = str(data.get("id", ""))
        logger.info("SMS sent to %s via number %s: %s", to_formatted, nid, msg_id)
        return {"ok": True, "message_id": msg_id, "to": to_formatted, "from_number_id": nid}
    except httpx.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        body_text = getattr(e.response, "text", str(e))
        logger.error("send_sms error: %s %s", status, body_text[:300])
        return {"ok": False, "error": f"HTTP {status}", "detail": body_text[:300]}
    except Exception as e:
        logger.error("send_sms error: %r", e)
        return {"ok": False, "error": str(e)}
