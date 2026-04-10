"""Unit tests for SmartMoving client error handling."""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "libs"))


class TestGetOpportunity:

    def test_read_timeout_returns_error(self):
        from smartmoving.client import get_opportunity

        with patch("smartmoving.client.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ReadTimeout("timed out")
            result = get_opportunity("some-id")
            assert "error" in result
            assert "timed out" in result["error"]

    def test_connect_timeout_returns_error(self):
        from smartmoving.client import get_opportunity

        with patch("smartmoving.client.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ConnectTimeout("connect failed")
            result = get_opportunity("some-id")
            assert "error" in result

    def test_http_500_returns_error(self):
        from smartmoving.client import get_opportunity

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
