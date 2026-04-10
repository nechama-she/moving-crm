"""SmartMoving API client — opportunity lookups."""

import logging
import os

import httpx

SMARTMOVING_API_KEY = os.getenv("SMARTMOVING_API_KEY", "")
SMARTMOVING_BASE_URL = os.getenv("SMARTMOVING_BASE_URL", "https://api-public.smartmoving.com/v1/api")

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {"x-api-key": SMARTMOVING_API_KEY, "Cache-Control": "no-cache"}


def get_opportunity(opportunity_id: str) -> dict:
    """Fetch a single opportunity by ID.

    Returns {"data": {...}} or {"error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/opportunities/{opportunity_id}"
    try:
        resp = httpx.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        return {"data": resp.json()}
    except httpx.HTTPError as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None) if resp is not None else None
        body = getattr(resp, "text", str(e)) if resp is not None else str(e)
        return {"error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        return {"error": str(e)}
