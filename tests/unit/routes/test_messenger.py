"""Tests for GET /api/meta/messenger/{user_id} and POST /api/meta/messenger/{user_id}."""

import json
from unittest.mock import patch, MagicMock


class TestGetMessengerMessages:

    def test_returns_messages(self, messenger_client, mock_conversations_table):
        mock_conversations_table.query.return_value = {
            "Items": [
                {"user_id": "u1", "timestamp": 1000, "text": "hello", "platform": "messenger"},
                {"user_id": "u1", "timestamp": 2000, "text": "hi back", "platform": "messenger"},
            ]
        }
        resp = messenger_client.get("/api/meta/messenger/u1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["text"] == "hello"

    def test_returns_empty_list(self, messenger_client, mock_conversations_table):
        mock_conversations_table.query.return_value = {"Items": []}
        resp = messenger_client.get("/api/meta/messenger/u1")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_pagination(self, messenger_client, mock_conversations_table):
        mock_conversations_table.query.side_effect = [
            {"Items": [{"user_id": "u1", "timestamp": 1, "text": "a", "platform": "messenger"}],
             "LastEvaluatedKey": {"user_id": "u1"}},
            {"Items": [{"user_id": "u1", "timestamp": 2, "text": "b", "platform": "messenger"}]},
        ]
        resp = messenger_client.get("/api/meta/messenger/u1")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 2

    def test_dynamodb_error_returns_502(self, messenger_client, mock_conversations_table):
        from botocore.exceptions import ClientError
        mock_conversations_table.query.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "err"}}, "Query"
        )
        resp = messenger_client.get("/api/meta/messenger/u1")
        assert resp.status_code == 502


class TestPostMessengerMessage:

    @patch("routes.meta.messenger._get_page_token", return_value="fake-token")
    @patch("routes.meta.messenger.urllib.request.urlopen")
    def test_send_success(self, mock_urlopen, mock_token, messenger_client):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        resp = messenger_client.post(
            "/api/meta/messenger/u1",
            json={"message": "hey there", "page_id": "page123"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_empty_message_returns_400(self, messenger_client):
        resp = messenger_client.post(
            "/api/meta/messenger/u1",
            json={"message": "   ", "page_id": "page123"},
        )
        assert resp.status_code == 400

    def test_missing_page_id_returns_422(self, messenger_client):
        resp = messenger_client.post(
            "/api/meta/messenger/u1",
            json={"message": "hello"},
        )
        assert resp.status_code == 422

    @patch("routes.meta.messenger._get_page_token", return_value="fake-token")
    @patch("routes.meta.messenger.urllib.request.urlopen")
    def test_send_retries_on_http_error(self, mock_urlopen, mock_token, messenger_client):
        import urllib.error
        error_resp = MagicMock()
        error_resp.read.return_value = b"token expired"
        error_resp.code = 400
        http_error = urllib.error.HTTPError("url", 400, "Bad", {}, None)
        http_error.read = MagicMock(return_value=b"token expired")

        success_resp = MagicMock()
        success_resp.__enter__ = MagicMock(return_value=success_resp)
        success_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [http_error, success_resp]

        resp = messenger_client.post(
            "/api/meta/messenger/u1",
            json={"message": "retry test", "page_id": "page123"},
        )
        assert resp.status_code == 200
