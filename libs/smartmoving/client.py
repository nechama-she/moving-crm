"""SmartMoving API client — opportunity lookups."""

import logging
import os
from collections import defaultdict
from http import HTTPStatus
from itertools import count

import httpx

SMARTMOVING_API_KEY = os.getenv("SMARTMOVING_API_KEY", "")
SMARTMOVING_BASE_URL = os.getenv("SMARTMOVING_BASE_URL", "https://api-public.smartmoving.com/v1/api")

logger = logging.getLogger(__name__)
_REQUEST_SEQ = count(1)
_REQUEST_TOTAL = 0
_REQUEST_BY_STATUS = defaultdict(int)
_REQUEST_BY_METHOD = defaultdict(int)
_REQUEST_BY_ENDPOINT = defaultdict(int)


def reset_request_counters() -> None:
    """Reset SmartMoving request counters for the current run."""
    global _REQUEST_SEQ, _REQUEST_TOTAL
    _REQUEST_SEQ = count(1)
    _REQUEST_TOTAL = 0
    _REQUEST_BY_STATUS.clear()
    _REQUEST_BY_METHOD.clear()
    _REQUEST_BY_ENDPOINT.clear()


def get_request_counters() -> dict:
    """Return SmartMoving request counters for the current run."""
    return {
        "total": _REQUEST_TOTAL,
        "by_status": dict(sorted(_REQUEST_BY_STATUS.items())),
        "by_method": dict(sorted(_REQUEST_BY_METHOD.items())),
        "by_endpoint": dict(sorted(_REQUEST_BY_ENDPOINT.items())),
    }


def _log_http_request(resp: httpx.Response) -> None:
    """Log outbound SmartMoving request with a per-invocation sequence number."""
    global _REQUEST_TOTAL
    req = resp.request
    method = req.method.upper() if req and req.method else "GET"
    url = str(req.url) if req and req.url else ""
    endpoint = req.url.path if req and req.url else ""
    status_code = int(resp.status_code)
    try:
        reason = HTTPStatus(status_code).phrase
    except ValueError:
        reason = ""

    _REQUEST_TOTAL += 1
    _REQUEST_BY_STATUS[status_code] += 1
    _REQUEST_BY_METHOD[method] += 1
    _REQUEST_BY_ENDPOINT[endpoint] += 1

    seq = next(_REQUEST_SEQ)
    logger.info('%d. HTTP Request: %s %s "HTTP/1.1 %d %s"', seq, method, url, status_code, reason)


def _headers() -> dict:
    return {"x-api-key": SMARTMOVING_API_KEY, "Cache-Control": "no-cache"}


def get_opportunity(opportunity_id: str) -> dict:
    """Fetch a single opportunity by ID.

    Returns {"data": {...}} or {"error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/opportunities/{opportunity_id}"
    try:
        resp = httpx.get(url, headers=_headers(), timeout=15)
        _log_http_request(resp)
        resp.raise_for_status()
        return {"data": resp.json()}
    except httpx.HTTPError as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None) if resp is not None else None
        body = getattr(resp, "text", str(e)) if resp is not None else str(e)
        return {"error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def get_followup(opportunity_id: str, followup_id: str) -> dict:
    """Fetch one followup from SmartMoving.

    Returns {"data": {...}} or {"error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/premium/opportunities/{opportunity_id}/followups/{followup_id}"
    try:
        resp = httpx.get(url, headers=_headers(), timeout=15)
        _log_http_request(resp)
        resp.raise_for_status()
        return {"data": resp.json()}
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        status = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        return {"error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def update_followup(opportunity_id: str, followup_id: str, payload: dict) -> dict:
    """Update a followup note via SmartMoving API.

    Returns {"ok": True} or {"ok": False, "error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/premium/opportunities/{opportunity_id}/followups/{followup_id}"
    headers = {**_headers(), "Content-Type": "application/json-patch+json"}
    logger.info("SmartMoving PUT %s payload=%s", url, payload)
    try:
        resp = httpx.put(url, headers=headers, json=payload, timeout=15)
        _log_http_request(resp)
        logger.info("SmartMoving PUT response: status=%s body=%s", resp.status_code, resp.text[:500] if resp.text else "(empty)")
        resp.raise_for_status()
        return {"ok": True}
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        status = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        logger.error("SmartMoving update_followup error: %s %s", status, body[:300])
        return {"ok": False, "error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        logger.error("SmartMoving update_followup exception: %r", e)
        return {"ok": False, "error": str(e)}


def add_opportunity_note(opportunity_id: str, note: str) -> dict:
    """Attempt to add a note to an opportunity.

    This is best-effort because SmartMoving note endpoints vary by account setup.
    Returns {"ok": True} or {"ok": False, "error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/premium/opportunities/{opportunity_id}/notes"
    headers = {**_headers(), "Content-Type": "application/json"}
    payload = {"notes": note}
    logger.info("SmartMoving POST %s payload=%s", url, payload)
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=15)
        _log_http_request(resp)
        logger.info("SmartMoving add_opportunity_note: status=%s body=%s", resp.status_code, resp.text[:300] if resp.text else "(empty)")
        resp.raise_for_status()
        return {"ok": True}
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        code = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        return {"ok": False, "error": f"HTTP {code}: {body[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def update_opportunity_salesperson(opportunity_id: str, salesperson_id: str) -> dict:
    """Update opportunity assignee (sales person) in SmartMoving.

    Returns {"ok": True} or {"ok": False, "error": ...}.
    """
    if not SMARTMOVING_API_KEY:
        logger.error("SmartMoving update_opportunity_salesperson skipped: API key not set")
        return {"ok": False, "error": "API key not set"}
    url = f"{SMARTMOVING_BASE_URL}/premium/opportunities/{opportunity_id}"
    payload = {"salesPersonId": salesperson_id}
    masked_key = SMARTMOVING_API_KEY[:4] + "*" * (len(SMARTMOVING_API_KEY) - 8) + SMARTMOVING_API_KEY[-4:] if len(SMARTMOVING_API_KEY) > 8 else "****"
    headers = {
        "x-api-key": SMARTMOVING_API_KEY,
        "Cache-Control": "no-cache",
        "Content-Type": "application/json-patch+json",
    }
    log_headers = dict(headers)
    log_headers["x-api-key"] = masked_key
    logger.info(
        "SmartMoving request: method=PATCH url=%s headers=%s payload=%s",
        url,
        log_headers,
        payload,
    )
    try:
        resp = httpx.patch(url, headers=headers, json=payload, timeout=15)
        _log_http_request(resp)
        response_body = resp.text[:500] if resp.text else "(empty)"
        logger.info(
            "SmartMoving PATCH response: status=%s body=%s",
            resp.status_code,
            response_body,
        )
        resp.raise_for_status()
        return {"ok": True, "status": resp.status_code, "body": response_body}
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        status = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        logger.error("SmartMoving update_opportunity_salesperson error: %s %s", status, body[:300])
        return {"ok": False, "status": status, "body": body[:300], "error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        logger.error("SmartMoving update_opportunity_salesperson exception: %r", e)
        return {"ok": False, "error": str(e)}
