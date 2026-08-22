"""Publish compact CRM activity events to connected admin browsers."""

import os

import boto3


def publish_realtime_event(payload: dict) -> None:
    function_name = os.getenv("REALTIME_FUNCTION_NAME", "")
    if not function_name:
        return
    boto3.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=__import__("json").dumps({"action": "broadcast", "payload": payload}).encode(),
    )
