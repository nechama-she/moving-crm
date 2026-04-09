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

SMS_DAY3_TEMPLATE = os.getenv(
    "SMS_DAY3_TEMPLATE",
    "Hi {name}, I just wanted to check in and see if you're still planning your move. If you received another estimate, feel free to send it over. We have a match or beat policy and can beat a written quote from a reputable company by up to 10%.",
)
