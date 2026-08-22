from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

import pytest
from fastapi import HTTPException

mock_auth = MagicMock()
mock_auth.get_current_user = MagicMock()
sys.modules.setdefault("auth", mock_auth)

from routes import leads


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDb:
    def __init__(self, companies, lead_rows, users):
        self.rows = {
            leads.Company: companies,
            leads.Lead: lead_rows,
            leads.User: users,
        }

    def query(self, model):
        return FakeQuery(self.rows[model])


def make_db(*, rep_aircall_id="aircall-123", assigned_to="rep-1"):
    company = SimpleNamespace(id="company-1", phone="+1 (212) 555-0100")
    rep = SimpleNamespace(id="rep-1", aircall_number_id=rep_aircall_id)
    lead = SimpleNamespace(
        id="lead-1",
        company_id=company.id,
        phone="212-555-0199",
        assigned_to=assigned_to,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2),
    )
    return FakeDb([company], [lead], [rep])


@pytest.fixture(autouse=True)
def user_company_access(monkeypatch):
    monkeypatch.setattr(leads, "_get_user_company_ids", lambda user, db: ["company-1"])


def lookup(db, **body):
    return leads.get_assigned_rep_aircall_id(
        client_phone=body["client_phone"],
        company_phone=body["company_phone"],
        user=SimpleNamespace(id="user-1", role="admin"),
        db=db,
    )


def test_returns_assigned_reps_aircall_number_id_with_formatted_phones():
    result = lookup(
        make_db(),
        client_phone="+1 212 555 0199",
        company_phone="2125550100",
    )

    assert result == {"aircall_number_id": "aircall-123"}


def test_uses_most_recent_matching_lead():
    db = make_db()
    db.rows[leads.Lead].append(
        SimpleNamespace(
            id="lead-2",
            company_id="company-1",
            phone="(212) 555-0199",
            assigned_to="rep-2",
            created_at=datetime(2026, 2, 1),
            updated_at=datetime(2026, 2, 2),
        )
    )
    db.rows[leads.User].insert(0, SimpleNamespace(id="rep-2", aircall_number_id="aircall-new"))

    result = lookup(db, client_phone="2125550199", company_phone="2125550100")

    assert result == {"aircall_number_id": "aircall-new"}


@pytest.mark.parametrize(
    ("db", "detail"),
    [
        (FakeDb([], [], []), "Company not found"),
        (make_db(assigned_to=None), "Lead has no assigned rep"),
        (make_db(rep_aircall_id=""), "Assigned rep has no Aircall number ID"),
    ],
)
def test_returns_clear_not_found_errors(db, detail):
    with pytest.raises(HTTPException) as exc:
        lookup(db, client_phone="2125550199", company_phone="2125550100")

    assert exc.value.status_code == 404
    assert exc.value.detail == detail
