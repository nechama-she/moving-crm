"""Unit tests for day-3 export filtering and sheet write orchestration."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.modules["database"] = MagicMock()
sys.modules["libs.smartmoving"] = MagicMock()
sys.modules["libs.aircall"] = MagicMock()
sys.modules["gspread"] = MagicMock()
sys.modules["google"] = MagicMock()
sys.modules["google.oauth2"] = MagicMock()
sys.modules["google.oauth2.service_account"] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lead-followup"))

import services.day3_export as mod


class TestBuildRow:

    def test_build_row_maps_fields(self):
        lead = {
            "full_name": "John Doe",
            "phone": "555-1234",
            "email": "john@test.com",
            "pickup_zip": "60601",
            "delivery_zip": "60614",
            "move_size": "3 Bedroom",
            "company_name": "Gorilla Movers",
        }
        row = mod._build_row(lead)

        assert row[0] == "John Doe"        # client_name
        assert row[1] == "555-1234"        # client_phone
        assert row[2] == "60601"           # client_pickup
        assert row[3] == "60614"           # client_delivery
        assert row[4] == "3 Bedroom"       # move_size
        assert row[5] == "john@test.com"   # client_email
        assert row[6] == "Gorilla Movers"  # moving_company


class TestRunExport:

    def test_run_export_filters_status_zero_only(self):
        with patch.object(mod, "GOOGLE_SHEET_ID", "sheet-1"), \
             patch.object(mod, "_load_candidates", return_value=[
                 {"smartmoving_id": "sm-1", "company_name": "Gorilla", "full_name": "Lead 1", "phone": "111", "email": "a@test.com", "created_at": "2026-05-01"},
                 {"smartmoving_id": "sm-2", "company_name": "Gorilla", "full_name": "Lead 2", "phone": "222", "email": "b@test.com", "created_at": "2026-05-02"},
                 {"smartmoving_id": "sm-3", "company_name": "Gorilla", "full_name": "Lead 3", "phone": "333", "email": "c@test.com", "created_at": "2026-05-03"},
             ]), \
             patch.object(mod, "get_opportunity") as mock_get_opportunity, \
             patch.object(mod, "_write_rows", return_value={"worksheet_title": "Day3 Status 0", "rows_written": 2}) as mock_write_rows, \
             patch.object(mod, "get_request_counters", return_value={"total": 3}):
            mock_get_opportunity.side_effect = [
                {"data": {"leadStatus": "Priority 0", "status": 0}},
                {"data": {"leadStatus": "Priority 1", "status": 1}},
                {"data": {"leadStatus": None, "status": 0}},
            ]

            result = mod.run_export("daily")

        assert result["stats"]["candidates"] == 3
        assert result["stats"]["matched"] == 2
        assert result["stats"]["rows_written"] == 2
        mock_write_rows.assert_called_once()

    def test_run_export_counts_smartmoving_errors(self):
        with patch.object(mod, "GOOGLE_SHEET_ID", "sheet-1"), \
             patch.object(mod, "_load_candidates", return_value=[{"smartmoving_id": "sm-1"}]), \
             patch.object(mod, "get_opportunity", return_value={"error": "boom"}), \
             patch.object(mod, "_write_rows", return_value={"worksheet_title": "Day3 Status 0", "rows_written": 0}), \
             patch.object(mod, "get_request_counters", return_value={"total": 1}):
            result = mod.run_export("bootstrap")

        assert result["stats"]["errors"] == 1
        assert result["stats"]["rows_written"] == 0
