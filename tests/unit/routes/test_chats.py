from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

import pytest
from fastapi import HTTPException

mock_auth = MagicMock()
mock_auth.get_current_user = MagicMock()
sys.modules.setdefault("auth", mock_auth)

from routes import chats


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def options(self, *args):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, lead_rows):
        self.lead_rows = lead_rows

    def query(self, model):
        if model is chats.Lead:
            return FakeQuery(self.lead_rows)
        return FakeQuery([("company-1",)])


def test_timestamp_normalizes_milliseconds_and_seconds():
    assert chats._timestamp(1_777_000_000_000) == 1_777_000_000
    assert chats._timestamp(1_777_000_000) == 1_777_000_000


def test_sms_page_queries_timestamp_index_newest_first(monkeypatch):
    table = MagicMock()
    table.query.return_value = {"Items": [{"message_id": "m1"}], "LastEvaluatedKey": {"cursor": "next"}}
    monkeypatch.setattr(chats, "sms_messages_table", table)

    items, cursor = chats._query_sms_page({"cursor": "current"}, 20)

    assert items == [{"message_id": "m1"}]
    assert cursor == {"cursor": "next"}
    kwargs = table.query.call_args.kwargs
    assert kwargs["IndexName"] == "record-type-timestamp-index"
    assert kwargs["ScanIndexForward"] is False
    assert kwargs["Limit"] == 20
    assert kwargs["ExclusiveStartKey"] == {"cursor": "current"}


def test_cursor_preserves_dynamodb_number_types():
    meta_key = {"user_id": "meta-1", "timestamp": Decimal("123.456")}
    sms_key = {"phone_number": "+12125550199", "timestamp": Decimal("789")}

    decoded_meta, decoded_sms = chats._decode_cursor(chats._encode_cursor(meta_key, sms_key))

    assert decoded_meta == meta_key
    assert decoded_sms == sms_key
    assert isinstance(decoded_meta["timestamp"], Decimal)


def test_reads_more_pages_until_unique_conversation_limit(monkeypatch):
    company = SimpleNamespace(name="Moving Co", aircall_number_id="company-number-1")
    leads = [
        SimpleNamespace(
            id=f"lead-{number}", company_id="company-1", assigned_to=None,
            full_name=f"Client {number}", phone="", facebook_user_id=f"meta-{number}",
            company=company, assignee=None, created_at=datetime(2026, 1, number),
            updated_at=datetime(2026, 1, number),
        )
        for number in (1, 2)
    ]
    meta_pages = iter([
        ([{"user_id": "meta-1", "platform": "messenger", "text": "one", "timestamp": 1}], {"page": "2"}),
        ([{"user_id": "meta-1", "platform": "messenger", "text": "new one", "timestamp": 2}], {"page": "3"}),
        ([{"user_id": "meta-2", "platform": "messenger", "text": "two", "timestamp": 3}], None),
    ])
    monkeypatch.setattr(chats, "_user_company_ids", lambda user, db: ["company-1"])
    monkeypatch.setattr(
        chats,
        "_scan_page",
        lambda table, start_key, limit: next(meta_pages) if table is chats.conversations_table else ([], None),
    )

    result = chats.get_all_chats(
        cursor="", limit=2, source="meta", user=SimpleNamespace(id="admin-1", role="admin"), db=FakeDb(leads),
    )

    assert len(result["items"]) == 2
    assert {item["lead_id"] for item in result["items"]} == {"lead-1", "lead-2"}


def test_returns_all_conversations_from_final_full_batch(monkeypatch):
    company = SimpleNamespace(name="Moving Co")
    lead_rows = [
        SimpleNamespace(
            id=f"lead-{number}", company_id="company-1", assigned_to=None,
            full_name=f"Client {number}", phone="", facebook_user_id=f"meta-{number}",
            company=company, assignee=None, created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        for number in range(1, 28)
    ]
    pages = iter([
        ([{"user_id": f"meta-{number}", "platform": "messenger", "text": str(number), "timestamp": number} for number in range(1, 16)], {"page": "2"}),
        ([{"user_id": f"meta-{number}", "platform": "messenger", "text": str(number), "timestamp": number} for number in range(16, 28)], None),
    ])
    monkeypatch.setattr(chats, "_user_company_ids", lambda user, db: ["company-1"])
    monkeypatch.setattr(
        chats,
        "_scan_page",
        lambda table, start_key, limit: next(pages) if table is chats.conversations_table else ([], None),
    )

    result = chats.get_all_chats(
        cursor="", limit=20, source="meta", user=SimpleNamespace(id="admin-1", role="admin"), db=FakeDb(lead_rows),
    )

    assert len(result["items"]) == 27


def test_keeps_meta_and_sms_sources_separate(monkeypatch):
    company = SimpleNamespace(name="Moving Co")
    lead = SimpleNamespace(
        id="lead-1",
        company_id="company-1",
        assigned_to="rep-1",
        full_name="Jane Client",
        phone="(212) 555-0199",
        facebook_user_id="meta-1",
        company=company,
        assignee=SimpleNamespace(name="Alex Rep", aircall_number_id="rep-number-1"),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2),
    )
    monkeypatch.setattr(chats, "_user_company_ids", lambda user, db: ["company-1"])
    monkeypatch.setattr(
        chats,
        "_scan_page",
        lambda table, start_key, limit: ([
                {"user_id": "meta-1", "platform": "messenger", "text": "Old", "timestamp": 10},
                {"user_id": "meta-1", "platform": "messenger", "text": "Newest", "timestamp": 30},
                {"user_id": "meta-1", "platform": "instagram", "text": "Instagram", "timestamp": 20},
            ], None),
    )
    monkeypatch.setattr(
        chats,
        "_query_sms_page",
        lambda start_key, limit: ([{
            "phone_number": "+12125550199",
            "company_name": "Moving Co",
            "number_id": "rep-number-1",
            "sales_name": "Message Sender",
            "text": "SMS",
            "timestamp": 25,
            "direction": "received",
        }], None),
    )

    meta_result = chats.get_all_chats(
        cursor="",
        limit=20,
        source="meta",
        user=SimpleNamespace(id="admin-1", role="admin"),
        db=FakeDb([lead]),
    )
    sms_result = chats.get_all_chats(
        cursor="",
        limit=20,
        source="sms",
        user=SimpleNamespace(id="admin-1", role="admin"),
        db=FakeDb([lead]),
    )

    assert [item["platform"] for item in meta_result["items"]] == ["messenger", "instagram"]
    assert meta_result["items"][0]["message"] == "Newest"
    assert meta_result["items"][0]["rep"] == "Alex Rep"
    assert [item["platform"] for item in sms_result["items"]] == ["sms"]
    assert sms_result["items"][0]["rep"] == "Alex Rep"
    assert all(item["lead_id"] == "lead-1" for item in meta_result["items"] + sms_result["items"])


def test_sms_does_not_fall_back_to_phone_only(monkeypatch):
    lead = SimpleNamespace(
        id="lead-sean", company_id="company-1", assigned_to="sean",
        full_name="Shared Client", phone="18046374931", facebook_user_id="",
        company=SimpleNamespace(name="Moving Co", aircall_number_id="company-number"),
        assignee=SimpleNamespace(name="Sean", aircall_number_id="sean-number"),
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 2),
    )
    monkeypatch.setattr(chats, "_user_company_ids", lambda user, db: ["company-1"])
    monkeypatch.setattr(
        chats,
        "_query_sms_page",
        lambda start_key, limit: ([{
            "phone_number": "+18046374931",
            "number_id": "bushra-number",
            "sales_name": "Bushra A",
            "text": "Bushra message",
            "timestamp": 25,
            "direction": "sent",
        }], None),
    )

    result = chats.get_all_chats(
        cursor="", limit=20, source="sms",
        user=SimpleNamespace(id="admin-1", role="admin"), db=FakeDb([lead]),
    )

    assert result["items"] == []


def test_returns_empty_without_company_access(monkeypatch):
    monkeypatch.setattr(chats, "_user_company_ids", lambda user, db: [])

    result = chats.get_all_chats(
        source="meta",
        user=SimpleNamespace(id="admin-1", role="admin"),
        db=FakeDb([]),
    )

    assert result == {"items": [], "next_cursor": "", "has_more": False}


@pytest.mark.parametrize("role", ["sales_rep", "dispatch", "foreman"])
def test_rejects_non_admin_users(role):
    with pytest.raises(HTTPException) as exc:
        chats.get_all_chats(
            cursor="",
            limit=20,
            source="meta",
            user=SimpleNamespace(id="user-1", role=role),
            db=FakeDb([]),
        )

    assert exc.value.status_code == 403
