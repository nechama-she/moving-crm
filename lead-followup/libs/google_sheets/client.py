"""Google Sheets client — read lead data."""

import logging
import os
import tempfile

import boto3
import gspread

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SHEET_ID

logger = logging.getLogger(__name__)

_CREDS_PATH = None


def _get_credentials_path() -> str:
    """Return path to Google credentials file, fetching from SSM if needed."""
    global _CREDS_PATH
    if _CREDS_PATH and os.path.exists(_CREDS_PATH):
        return _CREDS_PATH

    # If the file already exists on disk (local dev), use it directly
    if os.path.exists(GOOGLE_CREDENTIALS_FILE):
        _CREDS_PATH = GOOGLE_CREDENTIALS_FILE
        return _CREDS_PATH

    # Fetch from SSM Parameter Store
    ssm_param = os.getenv("GOOGLE_CREDENTIALS_SSM", "/meta-webhook/GOOGLE_SHEETS_CREDENTIALS")
    client = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    resp = client.get_parameter(Name=ssm_param, WithDecryption=True)
    creds_json = resp["Parameter"]["Value"]

    # Write to /tmp for gspread
    path = os.path.join(tempfile.gettempdir(), "google-credentials.json")
    with open(path, "w") as f:
        f.write(creds_json)
    _CREDS_PATH = path
    logger.info("Loaded Google credentials from SSM parameter")
    return _CREDS_PATH


def read_sheet() -> list[dict]:
    """Read all rows from the configured Google Sheet as list of dicts."""
    creds_path = _get_credentials_path()
    gc = gspread.service_account(filename=creds_path)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    worksheet = sh.sheet1
    rows = worksheet.get_all_records()
    logger.info("Read %d rows from Google Sheet", len(rows))
    return rows
