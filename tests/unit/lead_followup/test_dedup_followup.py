"""Unit tests for Day 2/3 SMS dedup logic."""

import sys
import os
from unittest.mock import MagicMock

sys.modules["database"] = MagicMock()
sys.modules["config"] = MagicMock()
sys.modules["libs.aircall"] = MagicMock()
sys.modules["libs.smartmoving"] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lead-followup"))

import importlib
import services.followup as mod
importlib.reload(mod)

mod.SMS_MESSAGE_TEMPLATE = "Hi {name}, {company} here"
mod.SMS_DAY3_TEMPLATE = "Hi {name}, {company} day3"


def _lead_row(**overrides):
    row = {
        "id": 1,
        "full_name": "John Doe",
        "phone": "555-1234",
        "email": "john@test.com",
        "smartmoving_id": "opp-abc-123",
        "created_at": "2026-04-15T12:00:00",
        "created_time": "2026-04-15T12:00:00",
        "status": "new",
        "company_name": "Test Movers",
        "company_phone": "555-0000",
        "aircall_number_id": "num-1",
        "company_timezone": "America/New_York",
    }
    row.update(overrides)
    return row


def _opp_response(lead_status="Priority 0", status=0):
    return {"data": {"leadStatus": lead_status, "status": status}}


def _setup(leads=None):
    """Reset all mocks on the module before each test."""
    # get_company_timezones is imported INSIDE run(), so must be on sys.modules
    db = sys.modules["database"]
    db.get_company_timezones = MagicMock(return_value=[
        {"id": 1, "name": "Test Co", "timezone": "America/New_York"}
    ])
    db.get_leads_for_followup = MagicMock(return_value=leads or [_lead_row()])
    # These are imported at module top level, so set on both mod and db
    db.was_already_sent = MagicMock(return_value=False)
    db.record_sent_message = MagicMock()
    mod.get_leads_for_followup = db.get_leads_for_followup
    mod.was_already_sent = db.was_already_sent
    mod.record_sent_message = db.record_sent_message
    mod.get_opportunity = MagicMock(return_value=_opp_response())
    mod.send_sms = MagicMock(return_value={"ok": True, "message_id": "m1", "to": "555"})
    mod.find_number_id = MagicMock(return_value="num-1")


class TestDay2Day3Dedup:

    def test_first_run_sends_and_records(self):
        _setup()
        result = mod.run(days_back=1, dry_run=False)

        mod.was_already_sent.assert_called_with("opp-abc-123", "day_2", "aircall")
        mod.record_sent_message.assert_called_with("opp-abc-123", "day_2", "aircall")
        assert result["stats"]["sms_sent"] == 1

    def test_duplicate_run_skips_sms(self):
        _setup()
        mod.was_already_sent.return_value = True

        result = mod.run(days_back=1, dry_run=False)

        mod.send_sms.assert_not_called()
        mod.record_sent_message.assert_not_called()
        sms = result["results"][0]["sms"]
        assert sms["skipped"] is True
        assert sms["reason"] == "already_sent"

    def test_day3_uses_correct_label(self):
        _setup()
        result = mod.run(days_back=2, dry_run=False)

        mod.was_already_sent.assert_called_with("opp-abc-123", "day_3", "aircall")
        mod.record_sent_message.assert_called_with("opp-abc-123", "day_3", "aircall")

    def test_dry_run_does_not_record(self):
        _setup()
        result = mod.run(days_back=1, dry_run=True)

        mod.record_sent_message.assert_not_called()
        mod.send_sms.assert_not_called()
        assert result["results"][0]["sms"]["dry_run"] is True

    def test_failed_sms_does_not_record(self):
        _setup()
        mod.send_sms.return_value = {"ok": False, "error": "invalid_number"}

        result = mod.run(days_back=1, dry_run=False)

        mod.record_sent_message.assert_not_called()
        assert result["stats"]["sms_failed"] == 1

    def test_multiple_leads_dedup_independently(self):
        lead1 = _lead_row(full_name="Lead A", smartmoving_id="opp-1")
        lead2 = _lead_row(full_name="Lead B", smartmoving_id="opp-2")
        _setup(leads=[lead1, lead2])
        mod.was_already_sent.side_effect = lambda sid, mt, ch: sid == "opp-1"

        result = mod.run(days_back=1, dry_run=False)

        mod.record_sent_message.assert_called_once_with("opp-2", "day_2", "aircall")
        assert result["results"][0]["sms"]["skipped"] is True
        assert result["results"][1]["sms"]["sent"] is True
