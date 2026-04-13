import json
import logging
import urllib.request
import urllib.error

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import conversations_table

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/meta/messenger", tags=["Messenger"])

GRAPH_API_VERSION = "v18.0"
ACCOUNTS_API_VERSION = "v24.0"
GRAPH_API_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# ---------------------------------------------------------------------------
# SSM / page-token helpers
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


_page_token_cache: dict[str, str] = {}


def _get_page_token(page_id: str) -> str:
    if page_id in _page_token_cache:
        return _page_token_cache[page_id]
    user_token = _get_ssm("/meta-webhook/COMMENTS_DETECTION_USER_TOKEN")
    if not user_token:
        raise HTTPException(status_code=500, detail="Missing Meta user token")
    url = f"https://graph.facebook.com/{ACCOUNTS_API_VERSION}/me/accounts?access_token={user_token}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.exception("Failed to fetch page tokens from Meta")
        raise HTTPException(status_code=502, detail="Failed to fetch page token") from exc
    for page in data.get("data", []):
        if page.get("id") == page_id:
            token = page["access_token"]
            _page_token_cache[page_id] = token
            return token
    raise HTTPException(status_code=400, detail=f"Page {page_id} not found for this Meta user")


# ---------------------------------------------------------------------------
# GET  /{user_id}  — fetch Messenger messages
# ---------------------------------------------------------------------------

@router.get("/{user_id}")
def get_messenger_messages(user_id: str):
    """Fetch Messenger messages for a user from the conversations table."""
    try:
        items = []
        response = conversations_table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
            FilterExpression=Attr("platform").eq("messenger"),
            ScanIndexForward=True,
        )
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = conversations_table.query(
                KeyConditionExpression=Key("user_id").eq(user_id),
                FilterExpression=Attr("platform").eq("messenger"),
                ScanIndexForward=True,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        return {"messages": items}
    except ClientError as e:
        logger.error("DynamoDB conversations error: %s", e)
        raise HTTPException(status_code=502, detail="Could not fetch conversations")


# ---------------------------------------------------------------------------
# POST /{user_id}  — send Messenger message
# ---------------------------------------------------------------------------

class MessengerSendRequest(BaseModel):
    message: str
    page_id: str


@router.post("/{user_id}")
def send_messenger_message(user_id: str, req: MessengerSendRequest):
    """Send a Messenger message to a user."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    token = _get_page_token(req.page_id)
    url = f"{GRAPH_API_URL}/me/messages?access_token={token}"
    payload = {"recipient": {"id": user_id}, "message": {"text": req.message.strip()}}
    data = json.dumps(payload).encode("utf-8")
    http_req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_req, timeout=10) as resp:
            logger.info("Messenger sent to %s", user_id)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("Messenger send error %s: %s", exc.code, body)
        # Retry once with fresh token
        _page_token_cache.pop(req.page_id, None)
        token = _get_page_token(req.page_id)
        url = f"{GRAPH_API_URL}/me/messages?access_token={token}"
        http_req2 = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(http_req2, timeout=10) as resp2:
            logger.info("Messenger sent (retry) to %s", user_id)
    return {"ok": True}
