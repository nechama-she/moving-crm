import re
import logging

from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException

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
