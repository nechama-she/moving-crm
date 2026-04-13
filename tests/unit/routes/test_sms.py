"""Tests for GET /api/sms/{phone} and POST /api/sms/{phone}."""

import json
from unittest.mock import patch, MagicMock

from routes.sms import _phone_variants, _normalize_digits


class TestPhoneVariants:

    def test_10_digit(self):
        variants = _phone_variants("2403703417")
        assert "+12403703417" in variants
        assert "12403703417" in variants
        assert "2403703417" in variants

    def test_11_digit(self):
        variants = _phone_variants("12403703417")
        assert "+12403703417" in variants
        assert "2403703417" in variants

    def test_formatted(self):
        variants = _phone_variants("(240) 370-3417")
        assert "+12403703417" in variants
        assert "2403703417" in variants

    def test_normalize_digits(self):
        assert _normalize_digits("(240) 370-3417") == "2403703417"
        assert _normalize_digits("+12403703417") == "12403703417"


class TestGetSmsMessages:

    def test_returns_messages(self, sms_client, mock_sms_messages_table):
        mock_sms_messages_table.query.return_value = {
            "Items": [
                {"phone_number": "+12403703417", "timestamp": 1000, "text": "hi",
                 "message_id": "m1", "company_name": "Gorilla haulers", "direction": "received"},
            ]
        }
        resp = sms_client.get("/api/sms/2403703417")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) >= 1

    def test_returns_empty(self, sms_client, mock_sms_messages_table):
        mock_sms_messages_table.query.return_value = {"Items": []}
        resp = sms_client.get("/api/sms/5551234567")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_deduplicates(self, sms_client, mock_sms_messages_table):
        item = {"phone_number": "+12403703417", "timestamp": 1, "text": "dup",
                "message_id": "m1", "company_name": "Gorilla haulers"}
        mock_sms_messages_table.query.return_value = {"Items": [item]}
        resp = sms_client.get("/api/sms/2403703417")
        msgs = resp.json()["messages"]
        ids = [m["message_id"] for m in msgs]
        assert ids.count("m1") == 1

    def test_dynamodb_error_returns_502(self, sms_client, mock_sms_messages_table):
        from botocore.exceptions import ClientError
        mock_sms_messages_table.query.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "err"}}, "Query"
        )
        resp = sms_client.get("/api/sms/5551234567")
        assert resp.status_code == 502


class TestPostSms:

    @patch("routes.sms._get_ssm")
    @patch("routes.sms.urllib.request.urlopen")
    def test_send_success(self, mock_urlopen, mock_ssm, sms_client):
        mock_ssm.side_effect = lambda k: {"AIRCALL_API_ID": "id", "AIRCALL_API_TOKEN": "tok"}.get(
            k.split("/")[-1], ""
        )
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"id": "msg-123"}).encode()
        mock_urlopen.return_value = mock_resp

        resp = sms_client.post(
            "/api/sms/2403703417",
            json={"message": "test sms", "aircall_number_id": "num-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["message_id"] == "msg-123"

    def test_empty_message_returns_400(self, sms_client):
        resp = sms_client.post(
            "/api/sms/2403703417",
            json={"message": "", "aircall_number_id": "num-1"},
        )
        assert resp.status_code == 400

    def test_missing_aircall_number_returns_422(self, sms_client):
        resp = sms_client.post(
            "/api/sms/2403703417",
            json={"message": "hello"},
        )
        assert resp.status_code == 422

    @patch("routes.sms._get_ssm", return_value="")
    def test_missing_credentials_returns_500(self, mock_ssm, sms_client):
        resp = sms_client.post(
            "/api/sms/2403703417",
            json={"message": "test", "aircall_number_id": "num-1"},
        )
        assert resp.status_code == 500

    @patch("routes.sms._get_ssm")
    @patch("routes.sms.urllib.request.urlopen")
    def test_aircall_error_returns_502(self, mock_urlopen, mock_ssm, sms_client):
        import urllib.error
        mock_ssm.side_effect = lambda k: "val"
        http_error = urllib.error.HTTPError("url", 422, "Bad", {}, None)
        http_error.read = MagicMock(return_value=b"invalid number")
        mock_urlopen.side_effect = http_error
        resp = sms_client.post(
            "/api/sms/2403703417",
            json={"message": "test", "aircall_number_id": "num-1"},
        )
        assert resp.status_code == 502
