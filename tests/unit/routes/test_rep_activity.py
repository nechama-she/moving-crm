import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

mock_auth = MagicMock()
mock_auth.get_current_user = MagicMock()
sys.modules.setdefault("auth", mock_auth)

from routes import rep_activity


def test_rejects_non_admin_users():
    with pytest.raises(HTTPException) as exc:
        rep_activity.get_rep_activity(
            category="new",
            limit=50,
            offset=0,
            user=SimpleNamespace(role="sales_rep"),
            db=MagicMock(),
        )

    assert exc.value.status_code == 403


class FakeQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *args):
        return self

    def first(self):
        return self.row


class FakeUpdateDb:
    def __init__(self, lead, state=None):
        self.rows = [lead, state]
        self.added = None
        self.committed = False

    def query(self, model):
        return FakeQuery(self.rows.pop(0))

    def add(self, row):
        self.added = row

    def commit(self):
        self.committed = True


def test_message_update_creates_lead_state(monkeypatch):
    monkeypatch.setattr(rep_activity, "get_config", lambda: {"API_SECRET": "secret"})
    db = FakeUpdateDb(SimpleNamespace(id="lead-1"))
    request = SimpleNamespace(headers={"x-api-secret": "secret"})

    result = rep_activity.update_communication_state(
        rep_activity.CommunicationUpdate(
            lead_id="lead-1",
            channel="sms",
            direction="inbound",
            occurred_at="2026-08-21T15:28:00Z",
        ),
        request=request,
        db=db,
    )

    assert result == {"ok": True, "lead_id": "lead-1"}
    assert db.added.latest_inbound_message_at.isoformat() == "2026-08-21T15:28:00+00:00"
    assert db.added.latest_message_channel == "sms"
    assert db.committed is True


def test_call_update_requires_answered(monkeypatch):
    monkeypatch.setattr(rep_activity, "get_config", lambda: {"API_SECRET": "secret"})
    with pytest.raises(HTTPException) as exc:
        rep_activity.update_communication_state(
            rep_activity.CommunicationUpdate(
                lead_id="lead-1",
                channel="call",
                direction="inbound",
                occurred_at="2026-08-21T15:28:00Z",
            ),
            request=SimpleNamespace(headers={"x-api-secret": "secret"}),
            db=MagicMock(),
        )

    assert exc.value.status_code == 400
