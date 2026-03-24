"""Centralized configuration — all env vars and settings in one place."""

import os
from pathlib import Path


# SmartMoving
SMARTMOVING_API_KEY = os.getenv("SMARTMOVING_API_KEY", "")
SMARTMOVING_BASE_URL = os.getenv("SMARTMOVING_BASE_URL", "https://api-public.smartmoving.com/v1/api")

# Google Sheets
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", str(Path(__file__).parent / "google-credentials.json"))
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1cftSB2c_kyjR0ADdxJ_2RrJbJv8XdnUQ73PgHeztr6s")

# Aircall
AIRCALL_BASE_URL = os.getenv("AIRCALL_BASE_URL", "https://api.aircall.io/v1")
AIRCALL_LAMBDA_SOURCE = os.getenv("AIRCALL_LAMBDA_SOURCE", "meta_webhook")

# SMS
SMS_MESSAGE_TEMPLATE = os.getenv(
    "SMS_MESSAGE_TEMPLATE",
    "Hi {name}, thanks for your interest in {company}! We'd love to help with your move. Reply to this message or call us anytime.",
)
