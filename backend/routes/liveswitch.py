"""LiveSwitch OAuth connection endpoints."""

import base64
import hashlib
import json
import hmac
import os
import re
import secrets
import time
from datetime import datetime
from decimal import Decimal
from spark_processing import SparkProcessingLog
from spark_history import remember_report, report_history, activate_report
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


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0

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
    from models import LeadAttachment, PublicMoveUpload, LeadJob
    from public_move_sync import queue_files
    from uuid import uuid4
    from spark_history import REPORT_KEYS
    if not os.getenv('PUBLIC_MOVE_SYNC_QUEUE_URL', '').strip():
        raise HTTPException(503, 'Customer file sync worker is not configured')
    lead = db.query(Lead).filter_by(id=lead_id).with_for_update().one_or_none()
    if not lead:
        raise HTTPException(404, 'Lead not found')
    access = db.query(PublicMoveAccess).filter_by(lead_id=lead_id).first()
    if not access:
        raise HTTPException(409, 'Generate the customer page before running an inventory report.')
    from report_files import move_files
    files = move_files(access, db, all_lead=bool(body is not None and 'file_ids' in body))
    if body is not None and 'file_ids' in body:
        selected = body['file_ids']
        if not isinstance(selected, list) or any(not isinstance(value, str) for value in selected):
            raise HTTPException(400, 'Select valid files for this report.')
        if set(selected) - {file.id for file in files}:
            raise HTTPException(400, 'Selected files are no longer available on this move.')
        files = [file for file in files if file.id in set(selected)]
    if not files:
        raise HTTPException(400, 'Upload files to the move before running a report.')
    config = _connection_config()
    template_id = (body and body.get('sparkTemplateId')) or config.get('spark_template_id')
    if not template_id:
        raise HTTPException(400, 'No Spark template is configured. Choose one in Settings.')
    payload = {'sparkTemplateId': template_id, 'shareWith': ['anyone']}
    for key in ('tasks', 'shareWith'):
        if body and key in body:
            payload[key] = body[key]
    conversation = ensure_lead_conversation(lead, db, fresh=True)
    saved = db.get(LeadLiveSwitch, lead_id)
    details = json.loads(saved.details or '{}') if saved else {}
    job = db.get(LeadJob, access.job_id)
    details['report_customer_packing'] = job.customer_packing
    details['report_customer_package'] = job.customer_packing_package
    remember_report(details)
    details['carried_question_state'] = details.get('carried_question_state') or {key: details[key] for key in ('report_question_answers', 'question_original_rows', 'spark_inventory_snapshot') if key in details}
    for key in REPORT_KEYS:
        if key != 'carried_question_state':
            details.pop(key, None)
    details['report_customer_packing'] = job.customer_packing
    details['report_customer_package'] = job.customer_packing_package
    draft = details.get('inventory_draft') or {}
    details.update(report_list_body=draft.get('body'), report_list_rows=draft.get('rows', []),
                   report_list_cuft=draft.get('cuft', 0), report_list_weight=draft.get('weight', 0),
                   manual_rooms=draft.get('rooms', []), report_source='combined' if draft.get('rows') else 'liveswitch')
    details.update(conversation)
    details.pop('media_readiness_check', None)
    details.update(last_spark_id='pending-' + str(uuid4()), last_spark_status='queued',
                   last_spark_at=int(time.time()), spark_pricing_ready=False,
                   report_conversation=conversation, pending_spark_payload=payload,
                   report_files=[{'id': f.id, 'name': f.file_name, 'size': f.file_size} for f in files])
    remember_report(details)
    if not saved:
        saved = LeadLiveSwitch(lead_id=lead_id)
        db.add(saved)
    saved.details = json.dumps(details)
    for attachment in files:
        row = db.get(PublicMoveUpload, attachment.id)
        if row is None:
            row = PublicMoveUpload(attachment_id=attachment.id, access_id=access.id, request_id='report-' + attachment.id)
            db.add(row)
        row.synced_at = None
        row.sync_status = 'pending'
        row.sync_token = None
        row.sync_upload_url = None
        row.sync_error = None
    access.published_price = access.published_cuft = access.published_at = None
    db.commit()
    queue_files(access.id, db)
    return {'id': details['last_spark_id'], 'status': 'queued'}


def start_ready_report(lead_id: str, db: Session):
    """Start a queued run only after every snapshot file reaches its conversation."""
    from models import PublicMoveUpload
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=lead_id).populate_existing().with_for_update().first()
    details = json.loads(saved.details or '{}') if saved else {}
    payload = details.get('pending_spark_payload')
    if not payload:
        # A retry can arrive after the report was created but queueing its monitor failed.
        from customer_report_updates import queue_report_check
        queue_report_check(lead_id, db)
        return
    file_ids = [row['id'] for row in details.get('report_files', [])]
    rows = db.query(PublicMoveUpload).filter(PublicMoveUpload.attachment_id.in_(file_ids)).all()
    if len(rows) != len(file_ids) or any(not row.synced_at for row in rows):
        details['last_spark_status'] = 'failed' if any(row.sync_status == 'failed' for row in rows) else 'queued'
        saved.details = json.dumps(details)
        db.commit()
        return
    # Allow five minutes to ingest the last uploaded file before analysis.
    if rows:
        import math
        import boto3
        if details.get('media_readiness_check', {}).get('conversation_id') != details['id']:
            delay = 60 - (datetime.utcnow() - max(row.synced_at for row in rows)).total_seconds()
            boto3.client('sqs').send_message(
                QueueUrl=os.environ['PUBLIC_MOVE_SYNC_QUEUE_URL'],
                DelaySeconds=max(0, min(60, math.ceil(delay))),
                MessageBody=json.dumps({'check_media': details['id'], 'lead_id': lead_id}),
            )
            details['media_readiness_check'] = {'conversation_id': details['id'], 'status': 'scheduled',
                'expected_files': details.get('report_files', [])}
        remaining = 300 - (datetime.utcnow() - max(row.synced_at for row in rows)).total_seconds()
        if remaining > 0:
            if details.get('spark_start_queued_for') != details.get('last_spark_id'):
                boto3.client('sqs').send_message(
                    QueueUrl=os.environ['PUBLIC_MOVE_SYNC_QUEUE_URL'],
                    DelaySeconds=min(900, max(1, math.ceil(remaining))),
                    MessageBody=json.dumps({'start_report': details['last_spark_id'], 'lead_id': lead_id}),
                )
                details['spark_start_queued_for'] = details['last_spark_id']
            details['last_spark_status'] = 'queued'
            saved.details = json.dumps(details)
            db.commit()
            return
    result = _api_post(f"conversations/{details['id']}/sparks", payload)
    if not result.get('id'):
        raise HTTPException(502, 'LiveSwitch did not return a report ID.')
    old_id = details['last_spark_id']
    details['spark_history'] = [row for row in details.get('spark_history', []) if row.get('last_spark_id') != old_id]
    details.update(last_spark_id=result['id'], last_spark_status=result.get('status', 'queued'))
    details.pop('pending_spark_payload', None)
    remember_report(details)
    saved.details = json.dumps(details)
    db.commit()
    from customer_report_updates import queue_report_check
    queue_report_check(lead_id, db)


def fetch_and_extract_spark_report(share_url: str, processing=None) -> tuple[float | None, float | None, list[dict[str, object]]]:
    if not share_url:
        raise ValueError('Completed report has no share URL')
    report_id = share_url.split('/reports/')[-1].split('?')[0].strip()
    if not report_id:
        raise ValueError('Report URL has no report ID')
    api_url = f'https://api.scribe.production.liveswitch.com/api/public/reports/{report_id}'
    resp = httpx.get(api_url, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f'Report download returned HTTP {resp.status_code}')
    if processing:
        processing.mark('download', 'success', f'Report received (HTTP {resp.status_code})')
        processing.mark('extract', 'running')
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError('Report response is not a JSON object')

    cuft = None
    weight = None
    inventory_rows: list[dict[str, object]] = []

    # Method 1: from structuredResult items
    sr = data.get("structuredResult")
    if isinstance(sr, dict):
        for sec in sr.get("sections", []):
            if sec.get("id") == "item-list" and "rows" in sec:
                total_vol = 0.0
                total_wt = 0.0
                for row in sec["rows"]:
                    if row.get("going", True):
                        qty = _safe_float(row.get("quantity"))
                        u_vol = _safe_float(row.get("unit_volume"))
                        u_wt = _safe_float(row.get("unit_weight"))
                        row_cuft = round(qty * u_vol, 2)
                        total_vol += qty * u_vol
                        total_wt += qty * u_wt
                        name = str(row.get("item_name") or row.get("name") or row.get("item") or "").strip()
                        if name or qty > 0 or row_cuft > 0:
                            inventory_rows.append({
                                "name": name or "Item",
                                "room": str(row.get("room") or ""),
                                "weight": round(qty * u_wt, 2),
                                "cuft": row_cuft if row_cuft > 0 else 0.0,
                                "amount": round(qty, 2) if qty > 0 else 0.0,
                            })
                if total_vol > 0:
                    cuft = total_vol
                    weight = round(total_wt, 1)

    # Method 2: regex fallback on markdown
    if cuft is None:
        text = data.get("result", "")
        pattern = r'\|\s*\*{0,2}Total\*{0,2}\s*\|(?:[^|]*\|){5}\s*([0-9.,]+)\s*\|\s*([0-9.,]+)\s*\|'
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                cuft = float(m.group(1).replace(",", ""))
                weight = float(m.group(2).replace(",", ""))
            except ValueError:
                pass

    return cuft, weight, inventory_rows


def apply_spark_results_to_lead(lead_id: str, share_url: str, db: Session, expected_report_id: str | None = None, use_snapshot: bool = False) -> dict:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    saved = db.get(LeadLiveSwitch, lead.id)
    details = json.loads(saved.details) if saved and saved.details else {}

    if expected_report_id is not None and details.get('last_spark_id') != expected_report_id:
        return {'ok': False, 'detail': 'A different report is now current. Refresh to see its results.'}
    processing = SparkProcessingLog(details.get('last_spark_id'))
    processing.mark('download', 'running')
    processing.persist(db, lead_id)
    try:
        if use_snapshot or details.get('report_source') == 'manual':
            cuft, weight = details.get('spark_extracted_cuft'), details.get('spark_extracted_weight')
            inventory_rows = details.get('spark_inventory_snapshot', [])
            processing.mark('download', 'success', 'Using saved room inventory; no LiveSwitch request')
            processing.mark('extract', 'running')
        else:
            cuft, weight, inventory_rows = fetch_and_extract_spark_report(share_url, processing=processing)
            if details.get('report_source') == 'combined':
                if not cuft or cuft <= 0:
                    raise ValueError('No positive volume was found in the media report.')
                cuft += details.get('report_list_cuft', 0)
                weight = (weight or 0) + details.get('report_list_weight', 0)
                inventory_rows = inventory_rows + details.get('report_list_rows', [])
        if saved:
            # A new run/selection may have arrived while downloading this report.
            db.refresh(saved, with_for_update=True)
            current_details = json.loads(saved.details or '{}')
            if current_details.get('last_spark_id') != details.get('last_spark_id'):
                db.rollback()
                return {'ok': False, 'detail': 'A different report is now current. Refresh to see its results.'}
            details = current_details
        if (not cuft or cuft <= 0) and not details.get('question_original_rows'):
            raise ValueError('No positive volume could be extracted from structuredResult item-list rows or the report total')

        from inventory_questions import adjusted_inventory
        from models import Company
        question_company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
        inventory_rows, cuft, weight = adjusted_inventory(question_company, details, inventory_rows, cuft, weight, db)
        processing.mark('extract', 'success', f'{len(inventory_rows)} inventory rows; {cuft:g} cu ft')
        processing.mark('inventory', 'running')
        lead.volume = Decimal(str(cuft))
        if weight is not None:
            lead.weight = Decimal(str(weight))

        details["spark_extracted_id"] = details.get("last_spark_id")
        details["spark_extracted_cuft"] = cuft
        details["spark_extracted_weight"] = weight
        details["last_spark_share_url"] = share_url
        details["spark_inventory_snapshot"] = inventory_rows
        from models import LeadJob, LeadSparkInventoryItem
        job = db.query(LeadJob).filter_by(lead_id=lead.id).order_by(LeadJob.job_order).first()
        price = None
        if not job:
            raise ValueError('No job found for this lead')
        if job:
            db.query(LeadSparkInventoryItem).filter(LeadSparkInventoryItem.job_id == job.id).delete(synchronize_session=False)
            for index, row in enumerate(inventory_rows):
                db.add(LeadSparkInventoryItem(
                    job_id=job.id,
                    name=str(row.get("name") or "Item"),
                    cuft=Decimal(str(row.get("cuft") or 0)),
                    amount=Decimal(str(row.get("amount") or 0)),
                    sort_order=index,
                ))

            db.flush()
            processing.mark('inventory', 'success', f'{len(inventory_rows)} rows prepared for job {job.job_order}')
            processing.mark('pricing', 'running')
            from routes.pricing import calculate_and_save_lead_job_price
            price = calculate_and_save_lead_job_price(lead, job, db) if cuft > 0 else None
            if cuft <= 0: job.price = None
            if price is None:
                processing.mark('pricing', 'error', 'No price returned - click to view details',
                                'The pricing calculator returned no price. Check move volume, company, active pricing book, pickup/delivery matching, and configured rates.')
            else:
                processing.mark('pricing', 'success', f'Calculated ${price:,.2f}')
            processing.mark('publish', 'running')

        from models import PublicMoveAccess
        access = db.query(PublicMoveAccess).filter_by(lead_id=lead.id).first()
        if access:
            access.published_cuft = lead.volume
            if cuft <= 0: access.published_price = None
            if price is not None:
                access.published_price = job.price
                access.published_at = datetime.utcnow()

        processing.mark('inventory', 'success', f'{len(inventory_rows)} rows saved to job {job.job_order}')
        processing.mark('publish', 'success' if price is not None else 'skipped',
                        'Estimate saved' if price is not None else 'Inventory saved; no new estimate to publish')
        details["spark_pricing_ready"] = price is not None
        details.pop('notification_error', None)
        processing.finish()
        if saved:
            processing.attach(details)
            saved.details = json.dumps(details)
        db.commit()
        from realtime import publish_customer_update
        publish_customer_update(lead_id)
        return {
            "ok": True,
            "cuft": cuft,
            "weight": weight,
            "price": price,
            "inventory_count": len(inventory_rows),
            "job_id": job.id if job else None,
        }
    except Exception as exc:
        db.rollback()
        processing.fail(exc)
        processing.persist(db, lead_id)
        return {'ok': False, 'detail': 'Report processing failed. Your moving team can view the processing log in the CRM.'}


def select_spark_report(lead_id: str, report_id: str, db: Session):
    saved = db.get(LeadLiveSwitch, lead_id)
    if saved:
        db.refresh(saved, with_for_update=True)
    details = json.loads(saved.details or '{}') if saved else {}
    if details.get('last_spark_status') in ('queued', 'running'):
        raise HTTPException(409, 'Wait for the new report to finish before choosing an earlier report.')
    from models import LeadJob
    job = db.query(LeadJob).filter_by(lead_id=lead_id).order_by(LeadJob.job_order).first()
    if job:
        details['report_customer_packing'] = job.customer_packing
        details['report_customer_package'] = job.customer_packing_package
    try:
        activate_report(details, report_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if job:
        job.customer_packing = details.get('report_customer_packing')
        job.customer_packing_package = details.get('report_customer_package')
    # The selected report is pending import, even if it was imported previously.
    details.pop('spark_extracted_id', None)
    details['spark_pricing_ready'] = False
    saved.details = json.dumps(details)
    access = db.query(PublicMoveAccess).filter_by(lead_id=lead_id).first()
    if access:
        access.published_price = None
        access.published_cuft = None
        access.published_at = None
    db.commit()
    return apply_spark_results_to_lead(lead_id, details.get('last_spark_share_url', ''), db, expected_report_id=report_id)


@router.get('/leads/{lead_id}/report-history')
def get_report_history(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    saved = db.get(LeadLiveSwitch, lead.id)
    return {'reports': report_history(json.loads(saved.details or '{}') if saved else {}, staff=True)}


@router.post('/leads/{lead_id}/reports/{report_id}/select')
def select_report_endpoint(lead_id: str, report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    result = select_spark_report(lead.id, report_id, db)
    if not result.get('ok'):
        raise HTTPException(422, result.get('detail'))
    return result


@router.post('/leads/{lead_id}/report-events-token')
def report_events_token(lead_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import jwt
    lead = _get_visible_lead_or_404(lead_id, user, db)
    from auth import decode_access_token
    claims = decode_access_token(request.headers.get('authorization', '').split(' ', 1)[-1])
    from customer_report_updates import queue_report_check
    queue_report_check(lead.id, db)
    token = jwt.encode({'sub': f'report-updates:{user.id}', 'role': 'report_updates', 'purpose': 'report_updates',
                        'lead_id': lead.id, 'iss': os.getenv('JWT_ISSUER', 'moving-crm'),
                        'exp': min(int(claims['exp']), int(time.time()) + 7200)}, os.environ['JWT_SECRET'], algorithm='HS256')
    return {'token': token}


@router.get('/leads/{lead_id}/spark-processing')
def get_spark_processing(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    saved = db.get(LeadLiveSwitch, lead.id)
    details = json.loads(saved.details or '{}') if saved else {}
    processing = details.get('spark_processing')
    if processing and processing.get('report_id') != details.get('last_spark_id'):
        processing = None
    return {'processing': processing}


@router.get("/leads/{lead_id}/spark-inventory")
def get_lead_spark_inventory(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)

    from models import LeadJob, LeadSparkInventoryItem
    job = db.query(LeadJob).filter_by(lead_id=lead.id).order_by(LeadJob.job_order).first()
    if not job:
        return {"job_id": None, "rows": []}

    rows = db.query(LeadSparkInventoryItem).filter_by(job_id=job.id).order_by(
        LeadSparkInventoryItem.sort_order.asc(), LeadSparkInventoryItem.created_at.asc()
    ).all()
    return {
        "job_id": job.id,
        "rows": [row.to_dict() for row in rows],
    }


class ApplyReportBody(BaseModel):
    reportUrl: str | None = None


@router.post("/leads/{lead_id}/apply-spark-report")
def apply_spark_report_endpoint(
    lead_id: str,
    body: ApplyReportBody | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    saved = db.get(LeadLiveSwitch, lead.id)
    details = json.loads(saved.details) if saved and saved.details else {}
    url = (body and body.reportUrl) or details.get("last_spark_share_url")
    if not url and details.get("report_source") != "manual":
        raise HTTPException(400, "No Spark report URL provided or found for this lead.")
    res = apply_spark_results_to_lead(lead.id, url, db)
    if not res.get("ok"):
        raise HTTPException(400, res.get("detail", "Failed to apply spark report."))
    return res


@router.get("/leads/{lead_id}/spark-status")
def get_lead_spark_status(
    lead_id: str,
    cached_only: bool = False,
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
    if details.get('report_source') == 'manual':
        return {'spark': {'id': spark_id, 'status': 'completed', 'source': 'manual'},
                'cuft': details.get('spark_extracted_cuft'), 'weight': details.get('spark_extracted_weight')}
    if cached_only:
        return {'spark': {'id': spark_id, 'status': details.get('last_spark_status', 'queued'),
                          'shareUrl': details.get('last_spark_share_url')},
                'cuft': details.get('spark_extracted_cuft'), 'weight': details.get('spark_extracted_weight')}
    # File transfer must finish before asking LiveSwitch to analyze the new conversation.
    if details.get("pending_spark_payload"):
        start_ready_report(lead.id, db)
        details = json.loads(saved.details)
        spark_id = details.get("last_spark_id")
        if details.get("pending_spark_payload"):
            return {"spark": {"id": spark_id, "status": details.get("last_spark_status", "queued")}}
    # Poll LiveSwitch for latest status
    try:
        remote = _api_get(f"sparks/{spark_id}")
        db.refresh(saved, with_for_update=True)
        details = json.loads(saved.details)
        if details.get("last_spark_id") != spark_id:
            spark_id = details.get("last_spark_id")
            remote = None
        if isinstance(remote, dict) and "status" in remote:
            details["last_spark_status"] = remote.get("status")
            share_url = remote.get("shareUrl")
            if share_url:
                details["last_spark_share_url"] = share_url
            saved.details = json.dumps(details)
            db.commit()

            # Auto-extract and calculate price if report is completed
            if remote.get("status") == "completed" and share_url and details.get("spark_extracted_id") != spark_id:
                try:
                    apply_spark_results_to_lead(lead.id, share_url, db)
                    details = json.loads(saved.details)
                except Exception:
                    pass

            return {
                "spark": remote,
                "cuft": details.get("spark_extracted_cuft"),
                "weight": details.get("spark_extracted_weight"),
            }
    except Exception:
        pass
    return {
        "spark": {
            "id": spark_id,
            "status": details.get("last_spark_status", "queued"),
            "shareUrl": details.get("last_spark_share_url"),
        },
        "cuft": details.get("spark_extracted_cuft"),
        "weight": details.get("spark_extracted_weight"),
    }


def ensure_lead_conversation(lead: Lead, db: Session, fresh: bool = False) -> dict:
    saved = db.get(LeadLiveSwitch, lead.id)
    if saved and not fresh and json.loads(saved.details or "{}").get("id"):
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
    if fresh:
        return details
    if saved:
        existing = json.loads(saved.details or '{}')
        existing.update(details)
        details = existing
        saved.details = json.dumps(details)
    else:
        saved = LeadLiveSwitch(lead_id=lead.id, details=json.dumps(details))
        db.add(saved)
    db.commit()
    return details


@router.post("/leads/{lead_id}/conversation")
def ensure_conversation(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_not_dispatch_write(user)
    lead = _get_visible_lead_or_404(lead_id, user, db)
    # Lock the parent row so simultaneous opens cannot create duplicate conversations.
    db.query(Lead).filter(Lead.id == lead.id).with_for_update().one()
    return ensure_lead_conversation(lead, db)


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
