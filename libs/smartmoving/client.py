"""SmartMoving API client — opportunity lookups."""

import logging
import os
import re
import time
from urllib.parse import urlparse
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
_OPPORTUNITY_INCLUDE_PARAMS = {
    "IncludeTripInfo": "true",
    "IncludePayments": "true",
    "IncludeJobAddresses": "true",
    "IncludeFiles": "true",
    "IncludePhotos": "true",
    "IncludeDocuments": "true",
    "IncludeCharges": "true",
}


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


def _request(method_fn, *args, **kwargs) -> httpx.Response:
    """Execute an httpx request, retrying once on 429 using the server-specified wait."""
    for attempt in range(2):
        resp = method_fn(*args, **kwargs)
        _log_http_request(resp)
        if resp.status_code != 429 or attempt == 1:
            return resp
        wait = 60
        try:
            msg = resp.json().get("message", "")
            m = re.search(r"Try again in (\d+) seconds", msg, re.IGNORECASE)
            if m:
                wait = int(m.group(1))
        except Exception:
            pass
        wait += 5
        logger.warning("SmartMoving rate limit hit — waiting %ds before retry", wait)
        time.sleep(wait)
    return resp  # type: ignore[return-value]  # covered by loop above


def get_opportunity(opportunity_id: str) -> dict:
    """Fetch a single opportunity by ID.

    Returns {"data": {...}} or {"error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/opportunities/{opportunity_id}"
    try:
        resp = _request(httpx.get, url, headers=_headers(), params=_OPPORTUNITY_INCLUDE_PARAMS, timeout=15)
        resp.raise_for_status()
        return {"data": resp.json()}
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        status = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        return {"error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def get_opportunity_audit_activity(opportunity_id: str) -> dict:
    """Fetch audit activity rows for an opportunity.

    Returns {"data": [...]} or {"error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/opportunities/{opportunity_id}/audit-activity"
    try:
        resp = _request(httpx.get, url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            return {"error": f"Unexpected audit payload type: {type(payload).__name__}"}
        return {"data": payload}
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        status = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        return {"error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def get_opportunity_documents(opportunity_id: str) -> dict:
    """Fetch SmartMoving premium opportunity documents metadata.

    Returns {"data": ...} or {"error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/premium/opportunities/{opportunity_id}/documents"
    try:
        resp = _request(httpx.get, url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        return {"data": resp.json()}
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        status = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        return {"error": f"HTTP {status}: {body[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def _extract_filename_from_content_disposition(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if match:
        return match.group(1).strip().strip('"')
    match = re.search(r"filename=\"?([^\";]+)\"?", value, re.IGNORECASE)
    if match:
        return match.group(1).strip().strip('"')
    return ""


def _looks_like_html(content_type: str, body: bytes) -> bool:
    if "text/html" in (content_type or "").lower():
        return True
    snippet = body[:512].decode("utf-8", errors="ignore").lower()
    return "<html" in snippet or "<!doctype html" in snippet


def _fetch_binary(url: str) -> dict:
    try:
        resp = _request(httpx.get, url, headers=_headers(), timeout=20, follow_redirects=True)
        resp.raise_for_status()
        body = resp.content or b""
        content_type = resp.headers.get("content-type", "application/octet-stream")
        if _looks_like_html(content_type, body):
            return {"ok": False, "error": "HTML response (likely login page)", "status": resp.status_code}
        file_name = _extract_filename_from_content_disposition(resp.headers.get("content-disposition"))
        return {
            "ok": True,
            "content": body,
            "content_type": content_type,
            "file_name": file_name,
            "status": resp.status_code,
        }
    except httpx.HTTPError as e:
        r = getattr(e, "response", None)
        status = getattr(r, "status_code", None) if r is not None else None
        body = getattr(r, "text", str(e)) if r is not None else str(e)
        return {"ok": False, "error": f"HTTP {status}: {body[:300]}", "status": status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def download_opportunity_document(opportunity_id: str, document_id: str = "", document_url: str = "") -> dict:
    """Download SmartMoving document bytes server-side.

    Returns:
      {"ok": True, "content": bytes, "content_type": str, "file_name": str}
      or {"ok": False, "error": str}
    """
    opp_id = (opportunity_id or "").strip()
    doc_id = (document_id or "").strip()
    url = (document_url or "").strip()
    if not opp_id:
        return {"ok": False, "error": "Missing opportunity id"}

    candidates: list[str] = []
    if url and url.lower().startswith(("http://", "https://")):
        parsed = urlparse(url)
        # blob: URLs are browser-local and cannot be fetched by server.
        if parsed.scheme in ("http", "https"):
            candidates.append(url)

    base = SMARTMOVING_BASE_URL.rstrip("/")
    if doc_id:
        candidates.extend([
            f"{base}/premium/opportunities/{opp_id}/documents/{doc_id}/download",
            f"{base}/premium/opportunities/{opp_id}/documents/{doc_id}",
            f"{base}/premium/documents/{doc_id}/download",
            f"{base}/premium/documents/{doc_id}",
        ])

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result = _fetch_binary(candidate)
        if result.get("ok"):
            return result

    return {"ok": False, "error": "Unable to fetch document content from SmartMoving"}


def get_followup(opportunity_id: str, followup_id: str) -> dict:
    """Fetch one followup from SmartMoving.

    Returns {"data": {...}} or {"error": ...}.
    """
    url = f"{SMARTMOVING_BASE_URL}/premium/opportunities/{opportunity_id}/followups/{followup_id}"
    try:
        resp = _request(httpx.get, url, headers=_headers(), timeout=15)
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
        resp = _request(httpx.put, url, headers=headers, json=payload, timeout=15)
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
        resp = _request(httpx.post, url, headers=headers, json=payload, timeout=15)
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
        resp = _request(httpx.patch, url, headers=headers, json=payload, timeout=15)
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
