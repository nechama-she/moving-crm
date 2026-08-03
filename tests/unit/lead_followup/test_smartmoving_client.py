"""Unit tests for SmartMoving client error handling."""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "libs"))

from smartmoving.client import create_provider_lead, download_opportunity_file, get_opportunity


class TestGetOpportunity:

    def test_requests_all_opportunity_sections(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {}
        with patch("smartmoving.client.httpx.get", return_value=response) as mock_get:
            assert get_opportunity("some-id") == {"data": {}}

        assert mock_get.call_args.kwargs["params"] == {
            "IncludeTripInfo": "true",
            "IncludePayments": "true",
            "IncludeSurveys": "true",
            "IncludeJobAddresses": "true",
            "IncludeTasks": "true",
            "IncludeFiles": "true",
            "IncludePhotos": "true",
            "IncludeDocuments": "true",
            "IncludeCharges": "true",
            "IncludeDispatchInfo": "true",
        }

    def test_read_timeout_returns_error(self):
        with patch("smartmoving.client.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ReadTimeout("timed out")
            result = get_opportunity("some-id")
            assert "error" in result
            assert "timed out" in result["error"]

    def test_connect_timeout_returns_error(self):
        with patch("smartmoving.client.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ConnectTimeout("connect failed")
            result = get_opportunity("some-id")
            assert "error" in result

    def test_http_500_returns_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        )

        with patch("smartmoving.client.httpx.get", return_value=mock_resp):
            result = get_opportunity("some-id")
            assert "error" in result
            assert "500" in result["error"]


def test_opportunity_file_download_rejects_untrusted_hosts():
    with patch("smartmoving.client.httpx.get") as mock_get:
        result = download_opportunity_file("https://example.com/file.txt")

    assert result["ok"] is False
    mock_get.assert_not_called()


def test_create_provider_lead_returns_smartmoving_lead_id():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"leadId": "new-smartmoving-id"}

    with patch("smartmoving.client._request", return_value=response) as mock_request:
        result = create_provider_lead("provider-key", "branch-id", {"fullName": "Test Lead"})

    assert result["ok"] is True
    assert result["lead_id"] == "new-smartmoving-id"
    assert mock_request.call_args.kwargs["params"] == {
        "providerKey": "provider-key",
        "branchId": "branch-id",
    }


def test_create_provider_lead_requires_configuration():
    with patch("smartmoving.client._request") as mock_request:
        result = create_provider_lead("", "branch-id", {})

    assert result["ok"] is False
    mock_request.assert_not_called()
