import hmac
import json
import os
import re

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from auth import decode_access_token, get_current_user, is_token_valid, require_admin
from config import get_config
from database import SessionLocal
from lead_audit import begin_sql_capture, finish_sql_capture, record_lead_update_log
from models import Lead, User
from routes import auth, leads, system, sms, companies, users, smartmoving, followups, outreach, assignment, tasks, templates, pricing
from routes.meta import messenger, instagram

cfg = get_config()

# Fail fast: never run the API with an unconfigured/insecure JWT signing key.
if not os.getenv("JWT_SECRET"):
    raise RuntimeError(
        "JWT_SECRET is not set — refusing to start the API without a signing key."
    )

# ---------------------------------------------------------------------------
# Default-deny authentication guard
# ---------------------------------------------------------------------------
# Every route requires a valid Bearer JWT UNLESS it is explicitly public
# (login / health) or presents a valid service-to-service x-api-secret (lead
# intake, auto-assign — those endpoints re-validate the secret themselves).
# This makes "forgetting to add auth to a new route" fail closed, not open.
PUBLIC_PATHS = {"/api/health", "/api/auth/login"}


def _api_secret() -> str:
    return cfg.get("API_SECRET") or os.getenv("API_SECRET", "")


async def enforce_authentication(request: Request) -> None:
    if request.method == "OPTIONS":
        return  # CORS preflight — handled by CORSMiddleware
    if request.url.path in PUBLIC_PATHS:
        return

    # Service-to-service secret. Only a handful of endpoints honor it, and each
    # re-checks it; user-data routers below additionally require a real user so a
    # leaked api-secret cannot read PII.
    provided_secret = request.headers.get("x-api-secret")
    if provided_secret:
        expected = _api_secret()
        if expected and hmac.compare_digest(provided_secret, expected):
            return

    auth_header = request.headers.get("Authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token.strip() and is_token_valid(token.strip()):
        return

    raise HTTPException(status_code=401, detail="Not authenticated")


app = FastAPI(title="Moving CRM", dependencies=[Depends(enforce_authentication)])


def _audit_request_context(request: Request) -> tuple[str, str, str]:
    path = request.url.path
    lead_id = ""
    actor_user_id = ""
    actor_name = ""

    direct_match = re.match(r"^/api/leads/([0-9a-fA-F-]{36})(?:/|$)", path)
    db = SessionLocal()
    try:
        if direct_match:
            lead_id = direct_match.group(1)
        else:
            smartmoving_match = re.match(
                r"^/api/leads/(?:by-smartmoving|assign-by-name)/([^/]+)(?:/|$)",
                path,
            )
            if smartmoving_match:
                lead = db.query(Lead).filter(Lead.smartmoving_id == smartmoving_match.group(1)).first()
                lead_id = lead.id if lead else ""

        auth_header = request.headers.get("Authorization") or ""
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            try:
                actor_user_id = str(decode_access_token(token.strip()).get("sub") or "")
            except Exception:
                actor_user_id = ""
        if actor_user_id:
            actor = db.query(User).filter(User.id == actor_user_id).first()
            actor_name = actor.name if actor else ""
    finally:
        db.close()

    return lead_id, actor_user_id, actor_name


@app.middleware("http")
async def audit_lead_mutations(request: Request, call_next):
    should_audit = (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/leads")
        and not request.url.path.endswith("/logs")
    )
    if not should_audit:
        return await call_next(request)

    lead_id, actor_user_id, actor_name = _audit_request_context(request)
    raw_body = await request.body()
    content_type = request.headers.get("content-type") or ""
    if raw_body:
        if "application/json" in content_type:
            try:
                request_payload = json.loads(raw_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                request_payload = {"body": raw_body.decode("utf-8", errors="replace")}
        elif "multipart/form-data" in content_type:
            request_payload = {
                "content_type": content_type,
                "body_size": len(raw_body),
                "note": "Binary multipart body omitted from audit storage",
            }
        else:
            request_payload = {
                "content_type": content_type,
                "body": raw_body.decode("utf-8", errors="replace"),
            }
    else:
        request_payload = {}

    endpoint = request.url.path
    if request.url.query:
        endpoint += f"?{request.url.query}"

    sql_capture_token = begin_sql_capture()
    try:
        response = await call_next(request)
    except Exception as exc:
        sql_statements = finish_sql_capture(sql_capture_token)
        record_lead_update_log(
            lead_id=lead_id,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            method=request.method,
            endpoint=endpoint,
            request_payload=request_payload,
            response_status=500,
            error=str(exc),
            sql_statements=sql_statements,
        )
        raise
    sql_statements = finish_sql_capture(sql_capture_token)

    response_body = b"".join([chunk async for chunk in response.body_iterator])
    response_content_type = response.headers.get("content-type") or ""
    if response_body:
        if "application/json" in response_content_type:
            try:
                response_payload = json.loads(response_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                response_payload = {"body": response_body.decode("utf-8", errors="replace")}
        else:
            response_payload = {
                "content_type": response_content_type,
                "body_size": len(response_body),
                "body": response_body.decode("utf-8", errors="replace"),
            }
    else:
        response_payload = None

    if not lead_id and isinstance(response_payload, dict):
        response_lead_id = str(response_payload.get("lead_id") or "")
        if re.fullmatch(r"[0-9a-fA-F-]{36}", response_lead_id):
            lead_id = response_lead_id

    record_lead_update_log(
        lead_id=lead_id,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        method=request.method,
        endpoint=endpoint,
        request_payload=request_payload,
        external_response=response_payload,
        response_status=response.status_code,
        sql_statements=sql_statements,
    )
    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
        background=response.background,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cfg["CORS_ORIGINS"].split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(auth.router)
app.include_router(leads.router)
app.include_router(companies.router)
app.include_router(users.router)
# Previously unauthenticated (customer PII / message send). Now require a real user
# so the global guard's x-api-secret path cannot reach message/SMS data.
app.include_router(messenger.router, dependencies=[Depends(get_current_user)])
app.include_router(instagram.router, dependencies=[Depends(get_current_user)])
app.include_router(sms.router, dependencies=[Depends(get_current_user)])
# Triggers backend Lambda processing — admin only.
app.include_router(smartmoving.router, dependencies=[Depends(require_admin)])
app.include_router(followups.router)
app.include_router(outreach.router)
app.include_router(assignment.router)
app.include_router(tasks.router)
app.include_router(templates.router)
app.include_router(pricing.router)
app.include_router(system.router)
