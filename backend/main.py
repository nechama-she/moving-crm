import hmac
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from auth import get_current_user, is_token_valid, require_admin
from config import get_config
from routes import auth, leads, system, sms, companies, users, smartmoving, followups, outreach, assignment, tasks, templates
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
app.include_router(system.router)
