import re
import json
import logging
import urllib.request
import urllib.error
import base64

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import sms_messages_table

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["SMS"])


def _normalize_digits(phone: str) -> str:
    """Strip everything except digits from a phone number."""
    return re.sub(r"\D", "", phone)


def _phone_variants(phone: str) -> list[str]:
    """Generate common phone number formats to try as DynamoDB keys."""
    digits = _normalize_digits(phone)
    # If 11 digits starting with 1, also try 10-digit version and vice versa
    variants = set()
    if len(digits) == 11 and digits.startswith("1"):
        d10 = digits[1:]
        variants.update([
            f"+{digits}",           # +12403703417
            digits,                  # 12403703417
            d10,                     # 2403703417
            f"+1{d10}",             # +12403703417
            f"({d10[:3]}) {d10[3:6]}-{d10[6:]}",  # (240) 370-3417
            f"{d10[:3]}-{d10[3:6]}-{d10[6:]}",    # 240-370-3417
        ])
    elif len(digits) == 10:
        variants.update([
            f"+1{digits}",           # +12403703417
            f"1{digits}",            # 12403703417
            digits,                  # 2403703417
            f"({digits[:3]}) {digits[3:6]}-{digits[6:]}",
            f"{digits[:3]}-{digits[3:6]}-{digits[6:]}",
        ])
    else:
        variants.add(phone)
        variants.add(digits)
        if digits:
            variants.add(f"+{digits}")
    return list(variants)


@router.get("/sms/{phone}")
def get_sms_messages(phone: str):
    """Fetch SMS messages for a phone number from the sms_messages table.
    Tries multiple phone number formats and only returns Gorilla haulers messages."""
    try:
        variants = _phone_variants(phone)
        all_items = []
        seen_ids = set()

        for variant in variants:
            response = sms_messages_table.query(
                KeyConditionExpression=Key("phone_number").eq(variant),
                FilterExpression=Attr("company_name").eq("Gorilla haulers"),
                ScanIndexForward=True,
            )
            for item in response.get("Items", []):
                mid = item.get("message_id", "")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    all_items.append(item)
            while "LastEvaluatedKey" in response:
                response = sms_messages_table.query(
                    KeyConditionExpression=Key("phone_number").eq(variant),
                    FilterExpression=Attr("company_name").eq("Gorilla haulers"),
                    ScanIndexForward=True,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    mid = item.get("message_id", "")
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        all_items.append(item)

        all_items.sort(key=lambda x: x.get("timestamp", 0))
        return {"messages": all_items}
    except ClientError as e:
        logger.error("DynamoDB sms_messages error: %s", e)
        raise HTTPException(status_code=502, detail="Could not fetch SMS messages")


# ---------------------------------------------------------------------------
# SSM helper
# ---------------------------------------------------------------------------

_ssm_cache: dict[str, str] = {}


def _get_ssm(key: str) -> str:
    if key in _ssm_cache:
        return _ssm_cache[key]
    try:
        ssm = boto3.client("ssm", region_name="us-east-1")
        resp = ssm.get_parameter(Name=key, WithDecryption=True)
        val = resp["Parameter"]["Value"]
        _ssm_cache[key] = val
        return val
    except ClientError:
        logger.exception("Failed to get SSM param %s", key)
        return ""


# ---------------------------------------------------------------------------
# POST /sms/{phone}  — send SMS via Aircall
# ---------------------------------------------------------------------------

class SmsSendRequest(BaseModel):
    message: str
    aircall_number_id: str


@router.post("/sms/{phone}")
def send_sms(phone: str, req: SmsSendRequest):
    """Send an SMS message via Aircall."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    # Normalize phone to E.164 format for Aircall
    digits = _normalize_digits(phone)
    if len(digits) == 10:
        digits = "1" + digits
    to_number = f"+{digits}"
    api_id = _get_ssm("/meta-webhook/AIRCALL_API_ID")
    api_token = _get_ssm("/meta-webhook/AIRCALL_API_TOKEN")
    if not api_id or not api_token:
        raise HTTPException(status_code=500, detail="Missing Aircall credentials")
    creds = base64.b64encode(f"{api_id}:{api_token}".encode()).decode()
    url = f"https://api.aircall.io/v1/numbers/{req.aircall_number_id}/messages/native/send"
    body = json.dumps({"to": to_number, "body": req.message.strip()}).encode("utf-8")
    http_req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg_id = str(data.get("id", ""))
            logger.info("Aircall SMS sent to %s: id=%s", to_number, msg_id)
            return {"ok": True, "message_id": msg_id}
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        logger.error("Aircall SMS error %s: %s", exc.code, body_text)
        raise HTTPException(status_code=502, detail=f"Aircall error: {body_text}") from exc
