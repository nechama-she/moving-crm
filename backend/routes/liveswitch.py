"""LiveSwitch OAuth connection endpoints."""

import base64
import hashlib
import json
import hmac
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import boto3
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, Field

from auth import require_admin
from config import get_config
from models import User

router = APIRouter(prefix="/api/liveswitch", tags=["LiveSwitch"])

AUTHORIZE_URL = "https://id.liveswitch.com/authorize"
TOKEN_URL = "https://id.liveswitch.com/oauth/token"
AUDIENCE = "https://public-api.production.liveswitch.com/"
SCOPES = "openid profile email offline_access conversations conversations.write contacts webhooks webhooks.write spark-templates sparks sparks.write"
STATE_TTL_SECONDS = 300


def _connection_config() -> dict:
    # Read current credentials on each instance, including already-warm Lambdas.
    try:
        value = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1")).get_parameter(
            Name=_refresh_token_parameter().replace("LIVESWITCH_REFRESH_TOKEN", "LIVESWITCH_OAUTH_CONFIG"),
            WithDecryption=True,
        )["Parameter"]["Value"]
        return json.loads(value)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ParameterNotFound":
            raise HTTPException(503, "Could not read LiveSwitch settings. Please try again.") from exc
    except (BotoCoreError, ValueError) as exc:
        raise HTTPException(503, "Could not read LiveSwitch settings. Please try again.") from exc
    config = get_config()
    res = {key: str(config.get("LIVESWITCH_" + key.upper()) or os.getenv("LIVESWITCH_" + key.upper(), "")).strip()
            for key in ("client_id", "client_secret", "redirect_uri")}
    res["spark_template_id"] = str(config.get("LIVESWITCH_SPARK_TEMPLATE_ID") or os.getenv("LIVESWITCH_SPARK_TEMPLATE_ID", "")).strip()
    return res


def _settings() -> tuple[str, str, str]:
    config = _connection_config()
    client_id, client_secret, redirect_uri = (config.get(key, "") for key in ("client_id", "client_secret", "redirect_uri"))
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=503, detail="LiveSwitch OAuth is not configured")
    return client_id, client_secret, redirect_uri


class ConnectionSettings(BaseModel):
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str = Field(default="", max_length=2048)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    spark_template_id: str | None = Field(default=None, max_length=512)


@router.get("/settings")
def connection_status(admin: User = Depends(require_admin)):
    config = _connection_config()
    token_saved = False
    try:
        boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1")).get_parameter(
            Name=_refresh_token_parameter(), WithDecryption=False)
        token_saved = True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ParameterNotFound":
            raise HTTPException(503, "Could not check LiveSwitch connection.") from exc
    except BotoCoreError as exc:
        raise HTTPException(503, "Could not check LiveSwitch connection.") from exc
    return {"client_id": config.get("client_id", ""), "redirect_uri": config.get("redirect_uri", ""),
            "has_secret": bool(config.get("client_secret")), "authorization_saved": token_saved,
            "spark_template_id": config.get("spark_template_id", "")}


@router.put("/settings")
def save_connection_settings(body: ConnectionSettings, admin: User = Depends(require_admin)):
    old = _connection_config()
    values = {
        "client_id": body.client_id.strip(),
        "client_secret": body.client_secret.strip() or old.get("client_secret", ""),
        "redirect_uri": body.redirect_uri.strip(),
        "spark_template_id": (body.spark_template_id or "").strip(),
    }
    uri = urlsplit(values["redirect_uri"])
    if (not uri.hostname or uri.username or uri.password or uri.query or uri.fragment
            or uri.path not in ("/api/liveswitch/oauth/callback", "/liveswitch/callback")
            or not (uri.scheme == "https" or (uri.scheme == "http" and uri.hostname in ("localhost", "127.0.0.1")))):
        raise HTTPException(400, "Enter the CRM callback address ending in /liveswitch/callback or /api/liveswitch/oauth/callback.")
    if not values["client_id"] or not values["client_secret"]:
        raise HTTPException(400, "Enter the Client ID and Client Secret from the LiveSwitch email.")
    if values["client_id"] != old.get("client_id") and not body.client_secret.strip():
        raise HTTPException(400, "Enter the Client Secret for the new Client ID.")
    try:
        ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
        # Only invalidate token if credentials/redirect changed
        credentials_changed = (
            values["client_id"] != old.get("client_id") or
            (body.client_secret.strip() and values["client_secret"] != old.get("client_secret")) or
            values["redirect_uri"] != old.get("redirect_uri")
        )
        if credentials_changed:
            try:
                ssm.delete_parameter(Name=_refresh_token_parameter())
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ParameterNotFound":
                    raise
            _token_cache.update(value="", expires=0.0)

        ssm.put_parameter(
            Name=_refresh_token_parameter().replace("LIVESWITCH_REFRESH_TOKEN", "LIVESWITCH_OAUTH_CONFIG"),
            Value=json.dumps(values),
            Type="SecureString",
            Overwrite=True,
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(503, "Could not save LiveSwitch settings. Please try again.") from exc
    return {"saved": True}


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
def start_oauth(response: Response, admin: User = Depends(require_admin)):
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
    response.set_cookie("liveswitch_oauth_state", params["state"], max_age=STATE_TTL_SECONDS,
                        httponly=True, secure=redirect_uri.startswith("https://"), samesite="lax", path="/api/liveswitch/oauth")
    response.headers["Cache-Control"] = "no-store"
    return {"authorization_url": authorization_url}


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
):
    _validate_state(state)
    if not hmac.compare_digest(state, request.cookies.get("liveswitch_oauth_state", "")):
        raise HTTPException(400, "Connection attempt expired. Return to Settings and click Connect LiveSwitch again.")
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
    _token_cache.update(value="", expires=0.0)
    result = HTMLResponse(
        "<!doctype html><title>LiveSwitch connected</title>"
        "<main style='font-family:system-ui;padding:40px'>"
        "<h1>LiveSwitch connected</h1><p>Your CRM can now use LiveSwitch.</p><a href='/settings'>Return to Settings</a></main>",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    result.delete_cookie("liveswitch_oauth_state", path="/api/liveswitch/oauth")
    return result

# Lead conversation endpoints keep OAuth credentials on the server.
from threading import Lock
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from auth import get_current_user
from database import get_db
from models import Lead, LeadLiveSwitch, PublicMoveAccess, SalesRep, Company
from libs.aircall.client import send_sms, find_number_id
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
        client_id, client_secret, _ = _settings()
        credential_key = hashlib.sha256((client_id + "\n" + client_secret).encode()).hexdigest()
        if _token_cache["expires"] > time.time() and _token_cache.get("credential_key") == credential_key:
            return _token_cache["value"]
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
        _token_cache.update(value=token, credential_key=credential_key, expires=time.time() + max(0, int(data.get("expires_in", 300)) - 60))
        return token


def _api_get(path, params=None):
    try:
        response = httpx.get(
            AUDIENCE + "v1/" + path,
            params=params,
            headers={"Authorization": "Bearer " + _access_token(), "Accept": "application/json"},
            timeout=45,
        )
        if response.status_code == 401:
            raise HTTPException(503, "LiveSwitch authorization has expired. Ask an administrator to reconnect LiveSwitch.")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "LiveSwitch could not complete the request. Please try again.") from exc


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


@router.get("/spark-templates")
def list_spark_templates(admin: User = Depends(require_admin)):
    data = _api_get("spark-templates")
    # LiveSwitch returns either a list directly or an object containing an items/results array
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items") or data.get("results") or data.get("data") or [data]
    return []


@router.post("/leads/{lead_id}/run-spark")
def run_spark_on_conversation(
    lead_id: str,
    body: dict | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    return trigger_lead_spark(lead.id, body, db)


def trigger_lead_spark(lead_id: str, body: dict | None = None, db: Session = None):
    saved = db.get(LeadLiveSwitch, lead_id)
    if not saved:
        raise HTTPException(409, "Start the LiveSwitch conversation first")
    details = json.loads(saved.details)
    conversation_id = details.get("id")
    if not conversation_id:
        raise HTTPException(400, "Conversation ID is missing")

    config = _connection_config()
    template_id = (body and body.get("sparkTemplateId")) or config.get("spark_template_id")
    if not template_id:
        raise HTTPException(400, "No Spark template is configured. Choose one in Settings.")

    payload = {
        "sparkTemplateId": template_id,
        "shareWith": ["anyone"],
    }
    if body and "tasks" in body:
        payload["tasks"] = body["tasks"]
    if body and "shareWith" in body:
        payload["shareWith"] = body["shareWith"]

    result = _api_post(f"conversations/{conversation_id}/sparks", payload)
    
    # Save spark ID and status to the lead's LiveSwitch record
    spark_id = result.get("id") if isinstance(result, dict) else None
    if spark_id:
        details["last_spark_id"] = spark_id
        details["last_spark_status"] = result.get("status", "queued")
        details["last_spark_at"] = int(time.time())
        saved.details = json.dumps(details)
        db.commit()

    return result


@router.get("/leads/{lead_id}/spark-status")
def get_lead_spark_status(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    saved = db.get(LeadLiveSwitch, lead.id)
    if not saved:
        return {"spark": None}
    details = json.loads(saved.details)
    spark_id = details.get("last_spark_id")
    if not spark_id:
        return {"spark": None}
    # Poll LiveSwitch for latest status
    try:
        remote = _api_get(f"sparks/{spark_id}")
        if isinstance(remote, dict) and "status" in remote:
            details["last_spark_status"] = remote.get("status")
            if remote.get("shareUrl"):
                details["last_spark_share_url"] = remote.get("shareUrl")
            saved.details = json.dumps(details)
            db.commit()
            return {"spark": remote}
    except Exception:
        pass
    return {
        "spark": {
            "id": spark_id,
            "status": details.get("last_spark_status", "queued"),
            "shareUrl": details.get("last_spark_share_url"),
        }
    }


@router.post("/leads/{lead_id}/conversation")
def ensure_conversation(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    # Lock the parent row so simultaneous opens cannot create duplicate conversations.
    db.query(Lead).filter(Lead.id == lead.id).with_for_update().one()
    saved = db.get(LeadLiveSwitch, lead.id)
    if saved:
        return json.loads(saved.details)
    company = lead.company
    if company is None:
        company = db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    if company is None:
        raise HTTPException(400, "Select a default company in Settings to start LiveSwitch for an unassigned lead")
    company_phone = (company.phone or "").strip()
    if not company_phone:
        raise HTTPException(400, "Add a phone number to the sending company before starting LiveSwitch")
    quote_number = str(lead.quote_number or "").strip()
    public_move = db.query(PublicMoveAccess).filter_by(lead_id=lead.id).first()
    if public_move and not quote_number:
        conversation_name = lead.full_name
    else:
        conversation_name = quote_number
    if not quote_number and not public_move:
        if not (lead.smartmoving_id or "").strip():
            raise HTTPException(400, "Connect this lead to SmartMoving before starting LiveSwitch")
        opportunity_result = get_opportunity(lead.smartmoving_id)
        opportunity = opportunity_result.get("data")
        if opportunity_result.get("error") or not isinstance(opportunity, dict):
            raise HTTPException(502, "Could not retrieve the SmartMoving quote number. Please try again.")
        quote_number = str(opportunity.get("quoteNumber") or "").strip()
        if not quote_number:
            raise HTTPException(400, "This SmartMoving lead does not have a quote number yet")
        lead.quote_number = quote_number
    conversation_name = quote_number or conversation_name
    result = _api_post("conversations", {"type": "LiveConversation", "phone": company_phone, "name": conversation_name})
    if not result.get("id"):
        raise HTTPException(502, "LiveSwitch did not return a conversation ID")
    details = {key: result.get(key, "") for key in ("id", "hostJoinUrl", "participantJoinUrl", "conversationUrl", "embeddedConversationUrl")}
    details["name"] = conversation_name
    db.add(LeadLiveSwitch(lead_id=lead.id, details=json.dumps(details)))
    db.commit()
    return details


@router.post("/leads/{lead_id}/participant-sms")
def send_participant_sms(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    saved = db.get(LeadLiveSwitch, lead.id)
    if not saved:
        raise HTTPException(409, "Start the conversation first")
    link = str(json.loads(saved.details).get("participantJoinUrl") or "").strip()
    if not link:
        raise HTTPException(400, "The participant link is unavailable")
    phone = (lead.phone or "").strip()
    if not phone:
        raise HTTPException(400, "This lead has no phone number")

    rep = lead.assignee
    number_id = (rep.aircall_number_id or "").strip() if rep else ""
    if not number_id and rep and (rep.name or "").strip():
        sales_rep = db.query(SalesRep).filter(
            func.lower(func.trim(SalesRep.name)) == rep.name.strip().lower()
        ).first()
        if sales_rep:
            number_id = (sales_rep.aircall_number_id or "").strip()
    if not number_id and lead.company:
        number_id = (lead.company.aircall_number_id or "").strip()
        if not number_id and (lead.company.phone or "").strip():
            number_id = find_number_id(lead.company.phone)
    if not number_id:
        raise HTTPException(400, "No Aircall sending number is configured for the assigned rep or this company")

    result = send_sms(to=phone, text=f"Please click this link to join the live video call. {link}", number_id=number_id)
    if not result.get("ok"):
        raise HTTPException(502, result.get("detail") or result.get("error") or "Could not send SMS through Aircall")
    return {"ok": True, "message_id": result.get("message_id", "")}


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
    conversation_id = json.loads(saved.details)["id"]
    return _api_post(f"conversations/{conversation_id}/upload-urls/{kind}", [file.model_dump() for file in files])


class PanelUpload(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    content_type: str = Field(default="application/octet-stream", min_length=1, max_length=120)


def panel_upload_context(lead_id, body, user, db):
    from models import LeadAttachment
    from routes.leads import _safe_attachment_name, _ensure_attachment_link_columns
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    _ensure_attachment_link_columns(db)
    existing = db.get(LeadAttachment, body.request_id)
    if existing and (existing.lead_id != lead.id or existing.uploaded_by != user.id):
        raise HTTPException(409, "Upload ID is already in use")
    bucket = os.getenv("ATTACHMENTS_BUCKET", "").strip()
    if not bucket:
        raise HTTPException(503, "Upload storage is unavailable")
    name = _safe_attachment_name(body.name)
    key = f"public-pending/staff/{lead.id}/{user.id}/{body.request_id}/{name}"
    return lead, existing, bucket, key, name


@router.post("/leads/{lead_id}/prepare-upload")
def prepare_panel_upload(lead_id: str, body: PanelUpload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, existing, bucket, key, name = panel_upload_context(lead_id, body, user, db)
    if existing:
        return {"completed": True, "id": existing.id}
    signed = boto3.client("s3").generate_presigned_post(
        Bucket=bucket, Key=key, Fields={"Content-Type": body.content_type},
        Conditions=[{"Content-Type": body.content_type}, ["content-length-range", 1, body.size]], ExpiresIn=3600)
    return {"completed": False, "upload": signed}


@router.post("/leads/{lead_id}/finish-upload")
def finish_panel_upload(lead_id: str, body: PanelUpload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from models import LeadAttachment
    lead, existing, bucket, key, name = panel_upload_context(lead_id, body, user, db)
    if existing:
        return {"id": existing.id}
    s3 = boto3.client("s3")
    try:
        obj = s3.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        raise HTTPException(502, "The uploaded file could not be verified. Please retry.") from exc
    if obj["ContentLength"] != body.size or obj.get("ContentType") != body.content_type:
        raise HTTPException(400, "File content does not match its expected size.")
    destination = f"leads/{lead.id}/jobs/lead/crm/{body.request_id}/{name}"
    s3.copy({"Bucket": bucket, "Key": key}, bucket, destination, ExtraArgs={"ServerSideEncryption": "AES256"})
    row = LeadAttachment(id=body.request_id, lead_id=lead.id, file_name=name, content_type=body.content_type,
        file_size=body.size, file_blob=b"", external_url=f"s3://{bucket}/{destination}",
        is_external_link=True, external_source="crm_s3", uploaded_by=user.id)
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    try:
        s3.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass  # Storage lifecycle removes abandoned staging files.
    return {"id": row.id}
