"""Export day-3 SmartMoving status-0 leads to Google Sheets."""

import json
import logging
import os
import tempfile
import time
from datetime import datetime

import boto3
import gspread
from google.oauth2.service_account import Credentials

from database import get_company_timezones, get_leads_before_cutoff, get_leads_for_followup
from libs.smartmoving import get_opportunity, reset_request_counters, get_request_counters
from services.followup import compute_utc_window

logger = logging.getLogger(__name__)

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip() or "1cftSB2c_kyjR0ADdxJ_2RrJbJv8XdnUQ73PgHeztr6s"
GOOGLE_WORKSHEET_TITLE = os.getenv("GOOGLE_DAY3_WORKSHEET_TITLE", "Day3 Status 0")
GOOGLE_CREDENTIALS_SSM = os.getenv("GOOGLE_CREDENTIALS_SSM", "/meta-webhook/GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_CREDS_PATH = None


def _get_credentials_path() -> str:
    """Return path to Google credentials JSON, fetching from SSM if needed."""
    global _CREDS_PATH
    if _CREDS_PATH and os.path.exists(_CREDS_PATH):
        return _CREDS_PATH
    ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    resp = ssm.get_parameter(Name=GOOGLE_CREDENTIALS_SSM, WithDecryption=True)
    creds_json = resp["Parameter"]["Value"]
    path = os.path.join(tempfile.gettempdir(), "google-credentials.json")
    with open(path, "w") as f:
        f.write(creds_json)
    _CREDS_PATH = path
    logger.info("Loaded Google credentials from SSM")
    return _CREDS_PATH


def _get_sheet_client():
    credentials = Credentials.from_service_account_file(_get_credentials_path(), scopes=GOOGLE_SCOPES)
    return gspread.authorize(credentials)


def _get_or_create_worksheet(spreadsheet, title: str):
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=2000, cols=20)


def _headers() -> list[str]:
    return [
        "client_name",
        "client_phone",
        "client_pickup",
        "client_delivery",
        "move_size",
        "client_email",
        "moving_company",
    ]


def _build_row(lead: dict, export_mode: str, opportunity: dict) -> list[str]:
    customer = opportunity.get("customer") or {}
    branch = opportunity.get("branch") or {}
    move_size = opportunity.get("moveSize") or {}
    jobs = opportunity.get("jobs") or []
    job_addresses = (jobs[0].get("jobAddresses") or []) if jobs else []
    return [
        str(customer.get("name") or ""),
        str(customer.get("phoneNumber") or ""),
        str(job_addresses[0]) if len(job_addresses) > 0 else "",
        str(job_addresses[1]) if len(job_addresses) > 1 else "",
        str(move_size.get("name") or ""),
        str(customer.get("emailAddress") or ""),
        str(branch.get("name") or ""),
    ]


def _write_rows(rows: list[list[str]], export_mode: str) -> dict:
    if not GOOGLE_SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID is not configured")

    client = _get_sheet_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    worksheet = _get_or_create_worksheet(spreadsheet, GOOGLE_WORKSHEET_TITLE)

    if export_mode == "bootstrap":
        worksheet.clear()
        worksheet.append_rows([_headers(), *rows], value_input_option="RAW")
    else:
        existing_header = worksheet.row_values(1)
        if existing_header != _headers():
            worksheet.clear()
            worksheet.append_row(_headers(), value_input_option="RAW")
        if rows:
            worksheet.append_rows(rows, value_input_option="RAW")

    return {"worksheet_title": worksheet.title, "rows_written": len(rows)}


def _load_candidates(export_mode: str) -> list[dict]:
    all_rows = []
    for company in get_company_timezones():
        if export_mode == "bootstrap":
            _, cutoff_utc = compute_utc_window(company["timezone"], days_back=2)
            rows = get_leads_before_cutoff(cutoff_utc, company_id=company["id"])
        else:
            ws_utc, we_utc = compute_utc_window(company["timezone"], days_back=2)
            rows = get_leads_for_followup(ws_utc, we_utc, company_id=company["id"])
        all_rows.extend(rows)
    return all_rows


def run_export(export_mode: str, limit: int = 0) -> dict:
    if export_mode not in {"bootstrap", "daily"}:
        raise ValueError(f"Unsupported export_mode: {export_mode}")

    reset_request_counters()
    logger.info("Day3 export started: mode=%s limit=%s sheet=%s worksheet=%s", export_mode, limit or "none", GOOGLE_SHEET_ID, GOOGLE_WORKSHEET_TITLE)

    candidates = _load_candidates(export_mode)
    logger.info("Loaded %d candidate leads from DB", len(candidates))
    if limit:
        logger.info("Will stop after %d matched (status=0) rows", limit)

    rows = []
    filtered = 0
    errors = 0
    skipped_no_id = 0
    skipped_nonzero = 0

    for i, lead in enumerate(candidates, 1):
        if limit and filtered >= limit:
            logger.info("Reached limit of %d matched rows, stopping early", limit)
            break
        smartmoving_id = str(lead.get("smartmoving_id") or "").strip()
        if not smartmoving_id:
            skipped_no_id += 1
            continue
        logger.info("[%d/%d] Fetching SmartMoving opportunity %s for lead %s", i, len(candidates), smartmoving_id, lead.get("full_name") or lead.get("id"))
        opp_resp = get_opportunity(smartmoving_id)
        time.sleep(0.55)  # stay under 120 req/min SmartMoving rate limit
        if "error" in opp_resp:
            errors += 1
            logger.warning("[%d/%d] SmartMoving error for %s: %s", i, len(candidates), smartmoving_id, opp_resp["error"])
            continue
        opportunity = opp_resp["data"]
        status = opportunity.get("status")
        if status != 0:
            skipped_nonzero += 1
            logger.info("[%d/%d] Skipping %s — status=%s (not 0)", i, len(candidates), smartmoving_id, status)
            continue
        filtered += 1
        logger.info("[%d/%d] Matched %s — status=0, adding to sheet", i, len(candidates), smartmoving_id)
        rows.append(_build_row(lead, export_mode, opportunity))

    logger.info("Loop complete: matched=%d skipped_nonzero=%d skipped_no_id=%d errors=%d", filtered, skipped_nonzero, skipped_no_id, errors)
    logger.info("Writing %d rows to sheet...", len(rows))
    sheet_result = _write_rows(rows, export_mode)
    logger.info("Sheet write complete: worksheet=%s rows_written=%d", sheet_result["worksheet_title"], sheet_result["rows_written"])
    smartmoving_requests = get_request_counters()
    result = {
        "mode": export_mode,
        "stats": {
            "candidates": len(candidates),
            "matched": filtered,
            "errors": errors,
            "rows_written": sheet_result["rows_written"],
        },
        "sheet": sheet_result,
        "smartmoving_requests": smartmoving_requests,
    }
    logger.info("Day3 export result: %s", json.dumps(result, default=str))
    return result
