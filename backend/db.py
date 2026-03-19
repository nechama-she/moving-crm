import time
import logging

import boto3
from botocore.exceptions import ClientError

from config import get_config

logger = logging.getLogger("moving-crm")

cfg = get_config()

dynamodb = boto3.resource("dynamodb", region_name=cfg["AWS_REGION"])
leads_table = dynamodb.Table(cfg["DYNAMO_TABLE_NAME"])
conversations_table = dynamodb.Table("conversations")
sms_messages_table = dynamodb.Table("sms_messages")

# ---------------------------------------------------------------------------
# Leads cache — avoid rescanning DynamoDB on every request
# ---------------------------------------------------------------------------

_leads_cache: list = []
_leads_cache_time: float = 0
LEADS_CACHE_TTL = 30  # seconds


def get_all_leads() -> list:
    global _leads_cache, _leads_cache_time
    now = time.time()
    if _leads_cache and (now - _leads_cache_time) < LEADS_CACHE_TTL:
        return _leads_cache
    items = []
    response = leads_table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = leads_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    items.sort(key=lambda x: x.get("created_time", ""), reverse=True)
    _leads_cache = items
    _leads_cache_time = now
    return _leads_cache
