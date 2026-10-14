"""User-requested verification against source history; never runs on page reads."""
import time
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from libs.common.phone import phone_variants


def digits(value):
    value = "".join(c for c in str(value or "") if c.isdigit())
    return value[-10:]


def latest_message(table, channel, client, company, *, seconds=12):
    """Return the latest non-automated message only after checking all pages.

    An incomplete read raises; callers must keep the existing row in that case.
    """
    deadline = time.monotonic() + seconds
    partitions = sorted(set(phone_variants(client))) if channel == "sms" else [client]
    latest = None
    for partition in partitions:
        cursor = None
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Conversation history check exceeded its time budget")
            args = dict(KeyConditionExpression=Key("phone_number" if channel == "sms" else "user_id").eq(partition),
                        ConsistentRead=True, Limit=100)
            if cursor:
                args["ExclusiveStartKey"] = cursor
            page = table.query(**args)
            for item in page.get("Items", []):
                if item.get("record_type", "message") != "message":
                    continue
                if channel == "sms":
                    if digits(item.get("company_number")) != digits(company):
                        continue
                elif (str(item.get("page_id") or "").strip() != company or
                      str(item.get("platform") or "messenger").strip().lower() != channel):
                    continue
                role = str(item.get("role") or "").strip().lower()
                sender = str(item.get("sales_name") or "").strip().lower()
                direction = str(item.get("direction") or "").strip().lower()
                if role in {"ai", "assistant", "bot"} or sender in {"ai", "assistant", "bot"} or direction == "draft":
                    continue
                if direction in {"inbound", "received"} or role in {"user", "client", "customer"}:
                    direction = "inbound"
                elif direction in {"outbound", "sent"} or role in {"agent", "human", "sales", "sales_rep", "admin", "business", "page"}:
                    direction = "outbound"
                else:
                    # Unknown source formats must never be treated as proof of a reply.
                    direction = "unknown"
                try:
                    timestamp = float(item["timestamp"])
                    if timestamp > 10_000_000_000:
                        timestamp /= 1000
                    occurred = datetime.fromtimestamp(timestamp, timezone.utc)
                except (KeyError, TypeError, ValueError, OverflowError, OSError):
                    raise ValueError("Message history contains an invalid timestamp")
                # Ambiguous equal-time messages favor keeping the queue entry.
                rank = (occurred, direction != "outbound")
                if latest is None or rank > latest[0]:
                    latest = (rank, direction)
            cursor = page.get("LastEvaluatedKey")
            if not cursor:
                break
    return (latest[0][0], latest[1]) if latest else None
