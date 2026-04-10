"""Unit tests for followup qualification logic and timezone window calculation."""

import sys
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Mock heavy dependencies before importing followup
sys.modules["database"] = MagicMock()
sys.modules["libs"] = MagicMock()
sys.modules["libs.aircall"] = MagicMock()
sys.modules["libs.smartmoving"] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lead-followup"))

from services.followup import _should_send_sms, compute_utc_window


class TestShouldSendSms:

    def test_priority_0_status_0(self):
        assert _should_send_sms("Priority 0", 0) is True

    def test_priority_0_status_1(self):
        assert _should_send_sms("Priority 0", 1) is True

    def test_priority_0_status_3(self):
        assert _should_send_sms("Priority 0", 3) is True

    def test_priority_0_status_2_rejected(self):
        assert _should_send_sms("Priority 0", 2) is False

    def test_empty_status_qualifies(self):
        assert _should_send_sms("", 0) is True

    def test_none_status_qualifies(self):
        assert _should_send_sms(None, 1) is True

    def test_other_priority_rejected(self):
        assert _should_send_sms("Priority 1", 0) is False


class TestTimezoneWindow:
    """Test that compute_utc_window converts 6 PM local to correct UTC."""

    def test_eastern_6pm_is_22_utc(self):
        """6 PM EDT = 22:00 UTC."""
        ws, we = compute_utc_window("America/New_York", days_back=1)
        assert ws.hour == 22
        assert we.hour == 22
        assert we - ws == timedelta(days=1)

    def test_pacific_6pm_is_01_utc(self):
        """6 PM PDT = 01:00 UTC next day."""
        ws, we = compute_utc_window("America/Los_Angeles", days_back=1)
        assert ws.hour == 1
        assert we.hour == 1
        assert we - ws == timedelta(days=1)

    def test_chicago_6pm_is_23_utc(self):
        """6 PM CDT = 23:00 UTC."""
        ws, we = compute_utc_window("America/Chicago", days_back=1)
        assert ws.hour == 23
        assert we.hour == 23

    def test_days_back_2_shifts_window(self):
        """days_back=2 should shift window one more day back."""
        ws1, we1 = compute_utc_window("America/New_York", days_back=1)
        ws2, we2 = compute_utc_window("America/New_York", days_back=2)
        assert we1 - we2 == timedelta(days=1)
        assert ws1 - ws2 == timedelta(days=1)

    def test_window_is_24_hours(self):
        """Window should always be exactly 24 hours."""
        for tz in ["America/New_York", "America/Los_Angeles", "America/Chicago", "Europe/London"]:
            ws, we = compute_utc_window(tz, days_back=1)
            assert we - ws == timedelta(days=1), f"Failed for {tz}"

    def test_null_timezone_defaults_to_new_york(self):
        """None timezone should use America/New_York fallback."""
        ws, we = compute_utc_window(None, days_back=1)
        assert ws.hour == 22  # EDT
