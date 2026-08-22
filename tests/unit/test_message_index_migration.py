from types import SimpleNamespace

import pytest

import backend.migrate_message_indexes as migration


def test_dev_skips_without_contacting_aws(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setattr(migration.boto3, "client", lambda *args, **kwargs: pytest.fail("AWS must not be called in dev"))
    migration.migrate()


def test_active_index_must_have_exact_schema():
    correct = {
        "IndexName": migration.INDEX_NAME,
        "IndexStatus": "ACTIVE",
        "KeySchema": [
            {"AttributeName": "record_type", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
    }
    client = SimpleNamespace(describe_table=lambda **kwargs: {"Table": {"GlobalSecondaryIndexes": [correct]}})
    assert migration._index_is_active_and_correct(client, "sms_messages") is True

    wrong = {**correct, "KeySchema": [{"AttributeName": "record_type", "KeyType": "HASH"}]}
    bad_client = SimpleNamespace(describe_table=lambda **kwargs: {"Table": {"GlobalSecondaryIndexes": [wrong]}})
    with pytest.raises(RuntimeError, match="wrong key schema"):
        migration._index_is_active_and_correct(bad_client, "sms_messages")


def test_backfill_updates_only_records_missing_record_type():
    class FakeClient:
        def __init__(self):
            self.updated = []

        def scan(self, **kwargs):
            return {"Items": [
                {"phone_number": {"S": "+12025550100"}, "timestamp": {"N": "1"}},
                {"phone_number": {"S": "+12025550101"}, "timestamp": {"N": "2"}, "record_type": {"S": "message"}},
            ]}

        def update_item(self, **kwargs):
            self.updated.append(kwargs)

    client = FakeClient()
    assert migration._backfill_table(client, "sms_messages", "phone_number", "timestamp") == 1
    assert len(client.updated) == 1
    assert client.updated[0]["Key"]["phone_number"] == {"S": "+12025550100"}
    assert client.updated[0]["ExpressionAttributeValues"] == {":message": {"S": "message"}}
