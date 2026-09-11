"""LiveSwitch OAuth connection endpoints."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import boto3
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from auth import require_admin
from config import get_config
from models import User

router = APIRouter(prefix="/api/liveswitch", tags=["LiveSwitch"])

AUTHORIZE_URL = "https://id.liveswitch.com/authorize"
TOKEN_URL = "https://id.liveswitch.com/oauth/token"
AUDIENCE = "https://public-api.production.liveswitch.com/"
SCOPES = "openid profile email offline_access conversations conversations.write contacts webhooks webhooks.write"
STATE_TTL_SECONDS = 300


def _settings() -> tuple[str, str, str]:
    config = get_config()
    client_id = str(config.get("LIVESWITCH_CLIENT_ID") or os.getenv("LIVESWITCH_CLIENT_ID", "")).strip()
    client_secret = str(config.get("LIVESWITCH_CLIENT_SECRET") or os.getenv("LIVESWITCH_CLIENT_SECRET", "")).strip()
    redirect_uri = str(config.get("LIVESWITCH_REDIRECT_URI") or os.getenv("LIVESWITCH_REDIRECT_URI", "")).strip()
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=503, detail="LiveSwitch OAuth is not configured")
    return client_id, client_secret, redirect_uri


def _state_secret() -> bytes:
    value = os.getenv("JWT_SECRET", "")
    if not value:
        raise RuntimeError("JWT_SECRET is required for LiveSwitch OAuth state")
    return value.encode()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _create_state(user_id: str) -> str:
    payload = _b64encode(json.dumps({
        "sub": user_id,
        "exp": int(time.time()) + STATE_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(18),
    }, separators=(",", ":")).encode())
    signature = _b64encode(hmac.new(_state_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def _validate_state(state: str) -> dict:
    try:
        payload, signature = state.split(".", 1)
        expected = _b64encode(hmac.new(_state_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        decoded = json.loads(_b64decode(payload))
        if int(decoded.get("exp") or 0) < int(time.time()) or not decoded.get("sub"):
            raise ValueError("expired state")
        return decoded
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc


def _refresh_token_parameter() -> str:
    prefix = os.getenv("SSM_PREFIX", "/moving-crm/")
    return f"{prefix.rstrip('/')}/LIVESWITCH_REFRESH_TOKEN"


@router.get("/oauth/start")
def start_oauth(admin: User = Depends(require_admin)):
    client_id, _, redirect_uri = _settings()
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': SCOPES,
        'audience': AUDIENCE,
        'state': _create_state(admin.id),
    }
    authorization_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
    return {"authorization_url": authorization_url}


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
):
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    _validate_state(state)
    if error:
        detail = error_description.strip() or error
        raise HTTPException(status_code=400, detail=f"LiveSwitch authorization failed: {detail}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    client_id, client_secret, redirect_uri = _settings()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(TOKEN_URL, json={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            })
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach LiveSwitch token service") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="LiveSwitch rejected the authorization code")
    tokens = response.json()
    refresh_token = str(tokens.get("refresh_token") or "")
    if not refresh_token:
        raise HTTPException(status_code=502, detail="LiveSwitch did not return a refresh token")

    boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1")).put_parameter(
        Name=_refresh_token_parameter(),
        Value=refresh_token,
        Type="SecureString",
        Overwrite=True,
    )
    return HTMLResponse(
        "<!doctype html><title>LiveSwitch connected</title>"
        "<main style='font-family:system-ui;padding:40px'>"
        "<h1>LiveSwitch connected</h1><p>You can close this window and return to the CRM.</p></main>"
    )

# Lead conversation endpoints keep OAuth credentials on the server.
from threading import Lock
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from auth import get_current_user
from database import get_db
from models import Lead, LeadLiveSwitch
from libs.smartmoving.client import get_opportunity
from routes.leads import _get_visible_lead_or_404, _ensure_not_dispatch_write

_token_lock = Lock()
_token_cache = {"value": "", "expires": 0.0}


def _access_token():
    # A configured API bearer token supports the direct integration as well as OAuth.
    configured_token = str(get_config().get("LIVESWITCH_ACCESS_TOKEN") or os.getenv("LIVESWITCH_ACCESS_TOKEN", "")).strip()
    if configured_token:
        return configured_token
    with _token_lock:
        if _token_cache["expires"] > time.time():
            return _token_cache["value"]
        client_id, client_secret, _ = _settings()
        ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
        try:
            refresh = ssm.get_parameter(Name=_refresh_token_parameter(), WithDecryption=True)["Parameter"]["Value"]
        except Exception as exc:
            raise HTTPException(503, "Connect LiveSwitch in Settings before starting a conversation") from exc
        try:
            response = httpx.post(TOKEN_URL, json={"grant_type": "refresh_token", "refresh_token": refresh,
                "client_id": client_id, "client_secret": client_secret}, timeout=20)
            response.raise_for_status()
            data = response.json()
            token = data["access_token"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise HTTPException(502, "LiveSwitch connection needs to be reconnected in Settings") from exc
        if data.get("refresh_token") and data["refresh_token"] != refresh:
            ssm.put_parameter(Name=_refresh_token_parameter(), Value=data["refresh_token"], Type="SecureString", Overwrite=True)
        _token_cache.update(value=token, expires=time.time() + max(0, int(data.get("expires_in", 300)) - 60))
        return token


def _api_post(path, body):
    try:
        response = httpx.post(AUDIENCE + "v1/" + path, json=body,
            headers={"Authorization": "Bearer " + _access_token(), "Accept": "application/json"}, timeout=45)
        if response.status_code == 401:
            raise HTTPException(503, "LiveSwitch authorization has expired. Ask an administrator to reconnect LiveSwitch.")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "LiveSwitch could not complete the request. Please try again.") from exc


@router.post("/leads/{lead_id}/conversation")
def ensure_conversation(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    # Lock the parent row so simultaneous opens cannot create duplicate conversations.
    db.query(Lead).filter(Lead.id == lead.id).with_for_update().one()
    saved = db.get(LeadLiveSwitch, lead.id)
    if saved:
        return json.loads(saved.details)
    company_phone = (lead.company.phone or "").strip() if lead.company else ""
    if not company_phone:
        raise HTTPException(400, "Add a phone number to this lead's company first")
    if not (lead.smartmoving_id or "").strip():
        raise HTTPException(400, "Connect this lead to SmartMoving before starting LiveSwitch")
    opportunity_result = get_opportunity(lead.smartmoving_id)
    opportunity = opportunity_result.get("data")
    if opportunity_result.get("error") or not isinstance(opportunity, dict):
        raise HTTPException(502, "Could not retrieve the SmartMoving quote number. Please try again.")
    quote_number = str(opportunity.get("quoteNumber") or "").strip()
    if not quote_number:
        raise HTTPException(400, "This SmartMoving lead does not have a quote number yet")
    result = _api_post("conversations", {"type": "LiveConversation", "phone": company_phone, "name": quote_number})
    if not result.get("id"):
        raise HTTPException(502, "LiveSwitch did not return a conversation ID")
    details = {key: result.get(key, "") for key in ("id", "hostJoinUrl", "participantJoinUrl", "conversationUrl", "embeddedConversationUrl")}
    details["name"] = quote_number
    db.add(LeadLiveSwitch(lead_id=lead.id, details=json.dumps(details)))
    db.commit()
    return details


class UploadFileInfo(BaseModel):
    fileName: str = Field(min_length=1, max_length=255)
    contentType: str = Field(min_length=1, max_length=150)


@router.post("/leads/{lead_id}/upload-urls/{kind}")
def upload_urls(lead_id: str, kind: Literal["images", "videos", "documents"], files: list[UploadFileInfo],
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    saved = db.get(LeadLiveSwitch, lead.id)
    if not saved:
        raise HTTPException(409, "Start the conversation first")
    if not 1 <= len(files) <= 20:
        raise HTTPException(400, "Select between 1 and 20 files per batch")
    allowed = {"images": {"image/jpeg", "image/png", "image/webp"}, "videos": {"video/mp4", "video/quicktime"}, "documents": {"application/pdf"}}
    if any(file.contentType not in allowed[kind] for file in files):
        raise HTTPException(400, "Unsupported file type")
    conversation_id = json.loads(saved.details)["id"]
    return _api_post(f"conversations/{conversation_id}/upload-urls/{kind}", [file.model_dump() for file in files])
