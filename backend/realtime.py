"""Publish compact CRM activity events to connected admin browsers."""

import logging
import os
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("moving-crm")


def publish_customer_update(lead_id: str) -> None:
    # Invalidation only. Customer details still require a valid portal session.
    publish_realtime_event({'type': 'customer_move_updated', 'customer_lead_id': lead_id})
    publish_report_update(lead_id)


def publish_report_update(lead_id: str) -> None:
    publish_realtime_event({'type': 'report_updated', 'report_lead_id': lead_id})


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def publish_realtime_event(payload: dict) -> None:
    function_name = os.getenv("REALTIME_FUNCTION_NAME", "")
    if not function_name:
        return
    try:
        boto3.client("lambda").invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=__import__("json").dumps(
                {"action": "broadcast", "payload": payload},
                default=_json_default,
            ).encode(),
        )
    except (BotoCoreError, ClientError, TypeError, ValueError) as exc:
        logger.warning("Realtime publish failed without failing the primary request: %s", exc)
