"""Unit tests for followup_messages dedup logic."""

import sys
import os
from unittest.mock import MagicMock, patch

# Mock heavy dependencies before importing
sys.modules["database"] = MagicMock()
sys.modules["libs"] = MagicMock()
sys.modules["libs.aircall"] = MagicMock()
sys.modules["libs.smartmoving"] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lead-followup"))

import importlib
import services.followup_messages as mod
importlib.reload(mod)


def _followup_row(**overrides):
    row = {
        "note_id": "note-abc-123",
        "smartmoving_id": "sm-abc-123",
        "type": 1,
        "title": "Follow up call",
        "assigned_to_id": "user-1",
        "due_date_time": MagicMock(isoformat=lambda: "2026-04-17T10:00:00"),
        "completed_at_utc": None,
        "notes": "existing note",
        "completed": False,
        "lead_id": 1,
        "full_name": "John Doe",
        "phone": "555-1234",
        "facebook_user_id": None,
        "email": "john@test.com",
        "company_name": "Test Movers",
        "company_phone": "555-0000",
        "aircall_number_id": "num-1",
        "company_timezone": "America/New_York",
    }
    row.update(overrides)
    return row


def _setup(rows=None):
    db = sys.modules["database"]
    db.get_due_followups = MagicMock(return_value=rows or [])
    db.was_already_sent = MagicMock(return_value=False)
    db.record_sent_message = MagicMock()
    mod.get_due_followups = db.get_due_followups
    mod.was_already_sent = db.was_already_sent
    mod.record_sent_message = db.record_sent_message
    mod.update_followup = MagicMock(return_value={"ok": True})
    mod.send_sms = MagicMock(return_value={"ok": True, "message_id": "m1", "to": "555"})
    mod.find_number_id = MagicMock(return_value="num-1")


class TestFollowupMessagesDedup:

    def test_first_run_processes_and_records(self):
        row = _followup_row()
        _setup(rows=[row])

        result = mod.run_followup_messages(dry_run=True)

        assert result["stats"]["processed"] == 1
        assert result["stats"]["note_updated"] == 1
        mod.record_sent_message.assert_called_with("sm-abc-123", "followup_note-abc-123", "smartmoving_note")

    def test_duplicate_run_skips_entirely(self):
        row = _followup_row()
        _setup(rows=[row])
        mod.was_already_sent.return_value = True

        result = mod.run_followup_messages(dry_run=True)

        mod.update_followup.assert_not_called()
        assert result["stats"]["processed"] == 0
        assert result["results"][0]["result"] == "already_sent"

    def test_channel_dedup_skips_already_sent_channel(self):
        row = _followup_row()
        _setup(rows=[row])
        mod.was_already_sent.side_effect = lambda sm, mt, ch: ch == "aircall"

        result = mod.run_followup_messages(dry_run=False)

        mod.send_sms.assert_not_called()
        mod.update_followup.assert_called_once()
        assert result["stats"]["note_updated"] == 1

    def test_note_update_failure_not_recorded(self):
        row = _followup_row()
        _setup(rows=[row])
        mod.update_followup.return_value = {"ok": False, "error": "api_error"}

        result = mod.run_followup_messages(dry_run=True)

        assert result["stats"]["note_failed"] == 1
        mod.record_sent_message.assert_not_called()

    def test_multiple_followups_dedup_independently(self):
        row1 = _followup_row(note_id="note-1", smartmoving_id="sm-1", full_name="Lead A")
        row2 = _followup_row(note_id="note-2", smartmoving_id="sm-2", full_name="Lead B")
        _setup(rows=[row1, row2])
        mod.was_already_sent.side_effect = lambda sm, mt, ch: mt == "followup_note-1" and ch == "smartmoving_note"

        result = mod.run_followup_messages(dry_run=True)

        assert result["results"][0]["result"] == "already_sent"
        assert result["results"][1]["note_id"] == "note-2"
        assert result["stats"]["processed"] == 1
        assert result["stats"]["note_updated"] == 1

    def test_no_channels_skips_without_dedup_check(self):
        row = _followup_row(phone=None, facebook_user_id=None)
        _setup(rows=[row])

        result = mod.run_followup_messages(dry_run=True)

        assert result["results"][0]["result"] == "no_channels"
        assert result["stats"]["processed"] == 0

    def test_messenger_channel_records_on_send(self):
        row = _followup_row(phone=None, facebook_user_id="fb-user-123")
        _setup(rows=[row])

        result = mod.run_followup_messages(dry_run=False)

        calls = mod.record_sent_message.call_args_list
        channel_args = [c[0][2] for c in calls]
        assert "smartmoving_note" in channel_args
        assert "messenger" not in channel_args
