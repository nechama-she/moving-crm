"""Google Sheets client — read lead data."""

import logging

import gspread

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SHEET_ID

logger = logging.getLogger(__name__)


def read_sheet() -> list[dict]:
    """Read all rows from the configured Google Sheet as list of dicts."""
    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    worksheet = sh.sheet1
    rows = worksheet.get_all_records()
    logger.info("Read %d rows from Google Sheet", len(rows))
    return rows
