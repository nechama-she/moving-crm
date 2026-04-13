"""Tests for GET /api/meta/instagram/{user_id}."""


class TestGetInstagramMessages:

    def test_returns_messages(self, instagram_client, mock_conversations_table):
        mock_conversations_table.query.return_value = {
            "Items": [
                {"user_id": "u1", "timestamp": 1000, "text": "ig msg", "platform": "instagram"},
            ]
        }
        resp = instagram_client.get("/api/meta/instagram/u1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["platform"] == "instagram"

    def test_returns_empty_list(self, instagram_client, mock_conversations_table):
        mock_conversations_table.query.return_value = {"Items": []}
        resp = instagram_client.get("/api/meta/instagram/u1")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_pagination(self, instagram_client, mock_conversations_table):
        mock_conversations_table.query.side_effect = [
            {"Items": [{"user_id": "u1", "timestamp": 1, "text": "a", "platform": "instagram"}],
             "LastEvaluatedKey": {"user_id": "u1"}},
            {"Items": [{"user_id": "u1", "timestamp": 2, "text": "b", "platform": "instagram"}]},
        ]
        resp = instagram_client.get("/api/meta/instagram/u1")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 2

    def test_dynamodb_error_returns_502(self, instagram_client, mock_conversations_table):
        from botocore.exceptions import ClientError
        mock_conversations_table.query.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "err"}}, "Query"
        )
        resp = instagram_client.get("/api/meta/instagram/u1")
        assert resp.status_code == 502
