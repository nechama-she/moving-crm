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
    client_id = str(config.get("LIVESWITCH_CLIENT_ID") or "").strip()
    client_secret = str(config.get("LIVESWITCH_CLIENT_SECRET") or "").strip()
    redirect_uri = str(config.get("LIVESWITCH_REDIRECT_URI") or "").strip()
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
