"""Publish compact CRM activity events to connected admin browsers."""

import logging
import os
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("moving-crm")


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
