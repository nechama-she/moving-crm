"""Publish compact CRM activity events to connected admin browsers."""

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("moving-crm")


def publish_realtime_event(payload: dict) -> None:
    function_name = os.getenv("REALTIME_FUNCTION_NAME", "")
    if not function_name:
        return
    try:
        boto3.client("lambda").invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=__import__("json").dumps({"action": "broadcast", "payload": payload}).encode(),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Realtime publish failed without failing the primary request: %s", exc)
