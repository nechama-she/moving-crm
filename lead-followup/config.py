"""Centralized configuration — all env vars and settings in one place."""

import os


# SmartMoving
SMARTMOVING_API_KEY = os.getenv("SMARTMOVING_API_KEY", "")
SMARTMOVING_BASE_URL = os.getenv("SMARTMOVING_BASE_URL", "https://api-public.smartmoving.com/v1/api")

# Aircall
AIRCALL_BASE_URL = os.getenv("AIRCALL_BASE_URL", "https://api.aircall.io/v1")

# SMS
SMS_MESSAGE_TEMPLATE = os.getenv(
    "SMS_MESSAGE_TEMPLATE",
    "Hi {name}, thanks for your interest in {company}! We'd love to help with your move. Reply to this message or call us anytime.",
)
