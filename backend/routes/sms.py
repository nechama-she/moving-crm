import json
import logging
import urllib.request
import urllib.error
import base64

from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import sms_messages_table
from libs.common.phone import normalize_digits as _normalize_digits, phone_variants as _phone_variants
from libs.common.ssm import get_ssm_cached

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["SMS"])

@router.get("/sms/{phone}")
def get_sms_messages(phone: str, company_name: str | None = None):
    """Fetch SMS messages for a phone number from the sms_messages table.
    Tries multiple phone number formats. Filters by company_name if provided."""
    try:
        variants = _phone_variants(phone)
        all_items = []
        seen_ids = set()

        for variant in variants:
            query_kwargs: dict = {
                "KeyConditionExpression": Key("phone_number").eq(variant),
                "ScanIndexForward": True,
            }
            response = sms_messages_table.query(**query_kwargs)
            for item in response.get("Items", []):
                if company_name and item.get("company_name", "").lower() != company_name.lower():
                    continue
                mid = item.get("message_id", "")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    all_items.append(item)
            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = sms_messages_table.query(**query_kwargs)
                for item in response.get("Items", []):
                    if company_name and item.get("company_name", "").lower() != company_name.lower():
                        continue
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
    api_id = get_ssm_cached("/meta-webhook/AIRCALL_API_ID")
    api_token = get_ssm_cached("/meta-webhook/AIRCALL_API_TOKEN")
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
