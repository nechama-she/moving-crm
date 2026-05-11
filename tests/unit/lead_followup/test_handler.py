"""Unit tests for lead-followup handler logging."""

import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

# Mock heavy dependencies before importing handler
sys.modules["database"] = MagicMock()
sys.modules["libs"] = MagicMock()
sys.modules["libs.aircall"] = MagicMock()
sys.modules["libs.smartmoving"] = MagicMock()
sys.modules["services.day3_export"] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lead-followup"))


def _make_result(results):
    return {"stats": {"total": len(results)}, "results": results}


def _lead_result(name, phone="555-1234", lead_status="Priority 0", sms=None):
    return {
        "name": name,
        "email": "",
        "phone": phone,
        "opportunity_id": "opp-1",
        "smartmoving_status": 0,
        "lead_status": lead_status,
        "sms": sms,
    }


class TestHandlerLogging:

    @patch("services.followup.run")
    def test_sms_none_does_not_crash(self, mock_run):
        mock_run.return_value = _make_result([
            _lead_result("John Doe", sms=None),
        ])
        from handler import handler
        resp = handler({"days_back": 1}, None)
        assert resp["statusCode"] == 200

    @patch("services.followup.run")
    def test_sms_sent_true(self, mock_run):
        mock_run.return_value = _make_result([
            _lead_result("Jane Doe", sms={"sent": True, "message_id": "abc"}),
        ])
        from handler import handler
        resp = handler({"days_back": 1}, None)
        body = json.loads(resp["body"])
        assert body["days_back_1"]["results"][0]["sms"]["sent"] is True

    @patch("services.followup.run")
    def test_sms_sent_false(self, mock_run):
        mock_run.return_value = _make_result([
            _lead_result("Bob", sms={"sent": False, "error": "no_phone_number"}),
        ])
        from handler import handler
        resp = handler({"days_back": 1}, None)
        assert resp["statusCode"] == 200

    @patch("services.followup.run")
    def test_skipped_lead_no_sms_key(self, mock_run):
        mock_run.return_value = _make_result([
            {"name": "Skip Guy", "result": "skipped_no_id"},
        ])
        from handler import handler
        resp = handler({"days_back": 1}, None)
        assert resp["statusCode"] == 200

    @patch("services.followup.run")
    def test_error_lead(self, mock_run):
        mock_run.return_value = _make_result([
            {"name": "Err Lead", "opportunity_id": "x", "result": "error", "error": "timeout"},
        ])
        from handler import handler
        resp = handler({"days_back": 1}, None)
        assert resp["statusCode"] == 200

    @patch("services.followup.run")
    def test_default_runs_day2_and_day3(self, mock_run):
        mock_run.return_value = _make_result([])
        from handler import handler
        handler({}, None)
        assert mock_run.call_count == 2
        days = [c.kwargs["days_back"] for c in mock_run.call_args_list]
        assert 1 in days
        assert 2 in days

    @patch("services.followup.run")
    def test_explicit_days_back(self, mock_run):
        mock_run.return_value = _make_result([])
        from handler import handler
        handler({"days_back": 2}, None)
        assert mock_run.call_count == 1

    @patch("services.day3_export.run_export")
    def test_day3_export_bootstrap_mode(self, mock_export):
        mock_export.return_value = {"stats": {"rows_written": 3}}
        from handler import handler
        resp = handler({"mode": "day3_export_bootstrap"}, None)
        body = json.loads(resp["body"])
        assert body["day3_export_bootstrap"]["stats"]["rows_written"] == 3
        mock_export.assert_called_once_with("bootstrap")

    @patch("services.day3_export.run_export")
    def test_day3_export_daily_mode(self, mock_export):
        mock_export.return_value = {"stats": {"rows_written": 1}}
        from handler import handler
        resp = handler({"mode": "day3_export_daily"}, None)
        body = json.loads(resp["body"])
        assert body["day3_export_daily"]["stats"]["rows_written"] == 1
        mock_export.assert_called_once_with("daily")
