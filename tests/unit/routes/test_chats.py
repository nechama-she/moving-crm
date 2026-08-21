from datetime import datetime
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

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, lead_rows):
        self.lead_rows = lead_rows

    def query(self, model):
        if model is chats.Lead:
            return FakeQuery(self.lead_rows)
        return FakeQuery([("company-1",)])


def test_combines_platforms_and_orders_by_latest_message(monkeypatch):
    company = SimpleNamespace(name="Moving Co")
    lead = SimpleNamespace(
        id="lead-1",
        company_id="company-1",
        assigned_to="rep-1",
        full_name="Jane Client",
        phone="(212) 555-0199",
        facebook_user_id="meta-1",
        company=company,
        assignee=SimpleNamespace(name="Alex Rep"),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2),
    )
    monkeypatch.setattr(chats, "_user_company_ids", lambda user, db: ["company-1"])
    monkeypatch.setattr(
        chats,
        "_scan_page",
        lambda table, start_key, limit: ((
            [
                {"user_id": "meta-1", "platform": "messenger", "text": "Old", "timestamp": 10},
                {"user_id": "meta-1", "platform": "messenger", "text": "Newest", "timestamp": 30},
                {"user_id": "meta-1", "platform": "instagram", "text": "Instagram", "timestamp": 20},
            ]
            if table is chats.conversations_table
            else [
                {
                    "phone_number": "+12125550199",
                    "company_name": "Moving Co",
                    "text": "SMS",
                    "timestamp": 25,
                    "direction": "received",
                }
            ]
        ), None),
    )

    result = chats.get_all_chats(
        cursor="",
        limit=20,
        user=SimpleNamespace(id="admin-1", role="admin"),
        db=FakeDb([lead]),
    )

    assert [item["platform"] for item in result["items"]] == ["messenger", "sms", "instagram"]
    assert result["items"][0]["message"] == "Newest"
    assert result["items"][0]["rep"] == "Alex Rep"
    assert all(item["lead_id"] == "lead-1" for item in result["items"])


def test_returns_empty_without_company_access(monkeypatch):
    monkeypatch.setattr(chats, "_user_company_ids", lambda user, db: [])

    result = chats.get_all_chats(
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
            user=SimpleNamespace(id="user-1", role=role),
            db=FakeDb([]),
        )

    assert exc.value.status_code == 403
