import hmac
import json
import logging
import os
import re
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth import decode_access_token, get_current_user, is_token_valid, require_admin
from config import get_config
from database import SessionLocal
from lead_audit import begin_sql_capture, finish_sql_capture, record_lead_update_log
from models import AccessAuditLog, Lead, User
from routes import auth, leads, system, sms, companies, users, smartmoving, followups, outreach, assignment, tasks, templates, pricing, chats, unanswered_messages, duplication_rules, liveswitch, referral_assignment_rules, communication_associations, stats
from routes import public_moves, local_pricing
from routes.meta import messenger, instagram

logger = logging.getLogger("moving-crm.access")
cfg = get_config()

# Fail fast: never run the API with an unconfigured/insecure JWT signing key.
if not os.getenv("JWT_SECRET"):
    raise RuntimeError(
        "JWT_SECRET is not set - refusing to start the API without a signing key."
    )

# ---------------------------------------------------------------------------
# Default-deny authentication guard
# ---------------------------------------------------------------------------
# Every route requires a valid Bearer JWT UNLESS it is explicitly public
# (login / health) or presents a valid service-to-service x-api-secret (lead
# intake, auto-assign - those endpoints re-validate the secret themselves).
# This makes "forgetting to add auth to a new route" fail closed, not open.
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/liveswitch/oauth/callback"}


def _api_secret() -> str:
    return cfg.get("API_SECRET") or os.getenv("API_SECRET", "")


async def enforce_authentication(request: Request) -> None:
    if request.method == "OPTIONS":
        return  # CORS preflight - handled by CORSMiddleware
    if request.url.path == "/api/inventory" and request.method == "POST":
        return  # Middleware validates the inventory key before body parsing.
    if re.fullmatch(r"/api/public-moves/[0-9a-f-]{36}/(verify-options|send-code|verify|details|generate-inventory-report|walkthrough|reschedule|availability|files|prepare-upload|finish-upload)", request.url.path):
        return  # Each endpoint requires a scoped link and, where needed, verified session.
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
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path != "/api/auth/change-password":
            payload = decode_access_token(token.strip())
            db = SessionLocal()
            try:
                actor = db.query(User).filter(User.id == str(payload.get("sub") or "")).first()
                foreman_job_patch = (
                    request.method == "PATCH"
                    and re.fullmatch(r"/api/leads/[^/]+/jobs/[^/]+", request.url.path) is not None
                )
                foreman_file_upload = (
                    request.method == "POST"
                    and (
                        re.fullmatch(r"/api/leads/[^/]+/attachments", request.url.path) is not None
                        or re.fullmatch(r"/api/leads/[^/]+/jobs/[^/]+/attachments", request.url.path) is not None
                    )
                )
                if actor and actor.role == "foreman" and not (foreman_job_patch or foreman_file_upload):
                    raise HTTPException(status_code=403, detail="Foreman users are read-only")
            finally:
                db.close()
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


def _extract_client_ip(request: Request) -> str:
    # 1. CloudFront custom header
    cf_ip = request.headers.get("cloudfront-viewer-address") or request.headers.get("x-forwarded-for")
    if cf_ip:
        # x-forwarded-for can be a comma-separated list of IPs (client, proxy1, proxy2...)
        parts = [p.strip() for p in cf_ip.split(",")]
        # remove port if present like 1.2.3.4:5678
        first = parts[0].split(":")[0] if ":" in parts[0] and not parts[0].count(":") > 1 else parts[0]
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


def _extract_request_user(request: Request) -> tuple[str | None, str, str | None, str]:
    auth_header = request.headers.get("Authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        try:
            payload = decode_access_token(token.strip())
            sub = str(payload.get("sub") or "")
            if sub:
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.id == sub).first()
                    if user:
                        return user.id, user.name, user.email, user.role
                finally:
                    db.close()
        except Exception:
            pass
    # Service secret?
    if request.headers.get("x-api-secret"):
        return None, "System Service", None, "system"
    return None, "Anonymous / Public", None, "anonymous"


@app.middleware("http")
async def track_access_history(request: Request, call_next):
    # Skip preflight OPTIONS and frequent internal healthchecks to keep logs meaningful
    if request.method == "OPTIONS" or request.url.path in {"/api/health"}:
        return await call_next(request)

    start_time = time.time()
    user_id, user_name, user_email, user_role = _extract_request_user(request)
    ip_address = _extract_client_ip(request)
    user_agent = request.headers.get("user-agent") or ""
    referer = request.headers.get("referer") or ""
    query_params = str(request.url.query) if request.url.query else None
    path = request.url.path

    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as exc:
        status_code = getattr(exc, "status_code", 500)
        raise
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        try:
            db = SessionLocal()
            log_row = AccessAuditLog(
                id=str(uuid4()),
                user_id=user_id,
                user_name=user_name,
                user_email=user_email,
                user_role=user_role,
                ip_address=ip_address[:100],
                method=request.method,
                path=path[:1000],
                query_params=query_params[:2000] if query_params else None,
                status_code=status_code,
                duration_ms=duration_ms,
                user_agent=user_agent[:1000] if user_agent else None,
                referer=referer[:1000] if referer else None,
            )
            db.add(log_row)
            db.commit()
            db.close()
        except Exception as log_err:
            logger.warning("Could not persist access audit log: %s", log_err)


@app.middleware("http")
async def protect_public_move_responses(request: Request, call_next):
    if request.url.path == "/api/inventory" and request.method == "POST":
        expected = public_moves.setting("PUBLIC_MOVE_API_KEY")
        provided = request.headers.get("x-api-secret", "")
        # Reject before FastAPI parses JSON or validates the request schema.
        if not expected or not hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8")):
            response = JSONResponse(status_code=401, content={"detail": "Not authorized"})
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    if request.url.path == "/api/inventory" or request.url.path.startswith("/api/public-move") or request.url.path.endswith("/customer-page"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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

    # Some endpoints generate the meaningful update payload server-side. Let the
    # handler replace an empty inbound body with that payload in the same audit row.
    audit_request_payload = getattr(request.state, "audit_request_payload", None)
    if audit_request_payload is not None:
        request_payload = audit_request_payload

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
app.include_router(chats.router)
app.include_router(unanswered_messages.router)
app.include_router(communication_associations.router)
app.include_router(stats.router)
app.include_router(duplication_rules.router)
app.include_router(referral_assignment_rules.router)
app.include_router(liveswitch.router)
app.include_router(public_moves.router)
# Triggers backend Lambda processing - admin only.
app.include_router(smartmoving.router, dependencies=[Depends(require_admin)])
app.include_router(followups.router)
app.include_router(outreach.router)
app.include_router(assignment.router)
app.include_router(tasks.router)
app.include_router(templates.router)
app.include_router(local_pricing.router)
app.include_router(pricing.router)
app.include_router(system.router)
