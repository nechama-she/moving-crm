"""Queue history performance regressions, without AWS credentials or network."""
import ast
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from unittest.mock import Mock
from types import SimpleNamespace
import sys

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Load, Session, joinedload

from boto3.dynamodb.conditions import Key

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from models import Base, Company, Lead, MessageState, MissedCallState, User, FirstContactState
from work_queue_rules import _digits, _epoch


@pytest.mark.parametrize("phone,expected", [
    ("(212) 555-1234", True),
    ("+1 907 555 1234", True),
    ("8085551234", True),
    ("+1 202 555 1234", True),
    ("+1 771 555 1234", True),
    ("+1 787 555 1234", False),
    ("+1 939 555 1234", False),
    ("+1 416 555 1234", False),
    ("+1 340 555 1234", False),
    ("+1 671 555 1234", False),
    ("+1 800 555 1234", False),
    ("+44 20 8366 1177", False),
    ("", False),
])
def test_followup_us_client_numbers(monkeypatch, phone, expected):
    source = Path(__file__).resolve().parents[2] / "backend/routes/unanswered_messages.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_is_us_client_phone"]
    scope = {}
    exec(compile(tree, str(source), "exec"), scope)
    assert scope["_is_us_client_phone"](phone) is expected


@pytest.mark.parametrize("smartmoving_id,created_here,history_result,should_check,should_add", [
    ("existing", False, False, True, True),
    ("existing", False, True, True, False),
    ("newly-created", True, False, False, True),
    (None, False, False, False, True),
    ("existing", False, TimeoutError("unavailable"), True, False),
])
def test_first_contact_checks_only_existing_smartmoving_leads(
        monkeypatch, smartmoving_id, created_here, history_result, should_check, should_add):
    import first_contact_state as state
    db = Mock()
    db.__enter__ = Mock(return_value=db)
    db.__exit__ = Mock(return_value=False)
    lead = SimpleNamespace(id="saved", priority=0, status="new", company=None,
                           smartmoving_id=smartmoving_id, created_time="2026-10-01T12:00:00Z")
    db.query.return_value.options.return_value.filter_by.return_value.first.return_value = lead
    db.get.return_value = None
    monkeypatch.setitem(sys.modules, "database", SimpleNamespace(SessionLocal=lambda: db))
    history = Mock(side_effect=history_result) if isinstance(history_result, Exception) else Mock(return_value=history_result)
    monkeypatch.setitem(sys.modules, "routes.unanswered_messages", SimpleNamespace(has_first_contact=history))
    state.add_created_lead("saved", created_in_smartmoving_here=created_here)
    assert history.call_count == int(should_check)
    if should_check:
        history.assert_called_once_with(lead, datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
    assert db.commit.call_count == int(should_add)
    assert db.execute.call_count == int(should_add)


def test_first_contact_page_reads_only_saved_pending_rows():
    source = Path(__file__).resolve().parents[2] / "backend/routes/unanswered_messages.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"list_first_contact_leads", "_queue_lead_options"}]
    for node in tree.body:
        node.decorator_list = []
        if node.name == "list_first_contact_leads":
            node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    ast.fix_missing_locations(tree)
    scope = dict(Lead=Lead, Company=Company, User=User, FirstContactState=FirstContactState,
                 Session=Session, Load=Load, joinedload=joinedload, datetime=datetime,
                 timezone=timezone, timedelta=timedelta)
    exec(compile(tree, str(source), "exec"), scope)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([Lead(id="pending", full_name="Pending", created_at=now-timedelta(hours=1)),
                    Lead(id="contacted", full_name="Contacted", created_at=now-timedelta(hours=1))])
        db.flush()
        waiting_since = now - timedelta(days=2)
        db.add(FirstContactState(lead_id="pending", waiting_since=waiting_since))
        db.commit()
        result = scope["list_first_contact_leads"](category="overdue", rep="", company="", refresh=False,
                                                    limit=50, offset=0, _=None, db=db)
        assert [row["lead_id"] for row in result["items"]] == ["pending"]
        assert result["global_counts"] == {"new": 0, "overdue": 1}
        assert result["items"][0]["created_at"] == waiting_since.isoformat()
        assert result["items"][0]["age_minutes"] >= 2 * 24 * 60
    engine.dispose()


def test_phoneless_messenger_contact_requires_human_reply_on_matching_page():
    source = Path(__file__).resolve().parents[2] / "backend/routes/unanswered_messages.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_has_human_messenger_contact"]
    table = Mock()
    scope = {"Key": Key, "_epoch": _epoch, "conversations_table": table}
    exec(compile(tree, str(source), "exec"), scope)
    lead = SimpleNamespace(facebook_user_id="client", company=SimpleNamespace(facebook_page_id="page"))
    created = datetime.fromtimestamp(1700000000, timezone.utc)
    records = [
        {"page_id": "page", "role": "agent", "timestamp": 1699999999000},
        {"page_id": "page", "role": "ai", "timestamp": 1700000001000},
        {"page_id": "other", "role": "agent", "timestamp": 1700000002000},
        {"page_id": "page", "role": "agent", "direction": "draft", "timestamp": 1700000003000},
    ]
    table.query.return_value = {"Items": records}
    check = scope["_has_human_messenger_contact"]
    assert not check(lead, created)
    table.query.side_effect = [
        {"Items": records, "LastEvaluatedKey": {"user_id": "client", "timestamp": 1700000003000}},
        {"Items": [{"page_id": "page", "role": "agent", "timestamp": 1700000004000}]},
    ]
    assert check(lead, created)
    assert "ExclusiveStartKey" in table.query.call_args.kwargs


def tracking_scope():
    source = Path(__file__).resolve().parents[2] / "backend/routes/unanswered_messages.py"
    functions = {"_digits", "_epoch", "_query_since", "_first_contact_tracking",
                 "_followup_call_tracking", "_load_call_tracking"}
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions]
    scope = dict(time=time, datetime=datetime, timezone=timezone, Key=Key, _digits=_digits, _epoch=_epoch,
                 COMMUNICATION_TIMESTAMP_INDEX="record-type-timestamp-index",
                 calls_table=Mock(), _call_tracking_lock=Lock(),
                 _first_contact_cache={"loaded_at": 0, "tracking_start": None, "contacts": {}},
                 _followup_calls_cache={"loaded_at": 0, "tracking_start": None, "calls": []})
    exec(compile(tree, str(source), "exec"), scope)
    return scope


def test_concurrent_queues_share_history_and_keep_latest_outbound_contact():
    scope = tracking_scope()
    calls = [
        {"timestamp": 100, "direction": "inbound", "phone_number": "2125550100", "company_number": "2125550200"},
        {"timestamp": 200, "direction": "outbound", "phone_number": "12125550100", "company_number": "2125550200"},
        {"timestamp": 300, "direction": "outbound", "phone_number": "2125550100", "company_number": "2125550200"},
    ]
    scope["calls_table"].query.side_effect = [{"Items": [{"timestamp": 100}]}, {"Items": calls}]
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(scope["_first_contact_tracking"])
        followup = executor.submit(scope["_followup_call_tracking"])
        start, contacts = first.result()
        followup_start, outbound = followup.result()
    assert start == followup_start == datetime.fromtimestamp(100, tz=timezone.utc)
    assert len(outbound) == 2
    assert contacts[("phone", "2125550100", "2125550200")] == datetime.fromtimestamp(300, tz=timezone.utc)
    assert scope["calls_table"].query.call_count == 2


def test_refreshed_history_invalidates_derived_first_contacts():
    scope = tracking_scope()
    scope["calls_table"].query.side_effect = [
        {"Items": [{"timestamp": 100}]}, {"Items": []},
        {"Items": [{"timestamp": 100}]},
        {"Items": [{"timestamp": 400, "direction": "outbound", "phone_number": "2125550100", "company_number": "2125550200"}]},
    ]
    assert scope["_first_contact_tracking"]()[1] == {}
    scope["_followup_calls_cache"]["loaded_at"] = 0
    assert len(scope["_first_contact_tracking"]()[1]) == 1


def test_empty_history_is_cached():
    scope = tracking_scope()
    scope["calls_table"].query.return_value = {"Items": []}
    assert scope["_first_contact_tracking"]() == (None, {})
    assert scope["_followup_call_tracking"]() == (None, [])
    scope["calls_table"].query.assert_called_once()


def test_projection_is_preserved_on_every_history_page():
    scope = tracking_scope()
    table = Mock()
    table.query.side_effect = [
        {"Items": [{"timestamp": 100}], "LastEvaluatedKey": {"pk": "next"}},
        {"Items": [{"timestamp": 200}]},
    ]
    assert scope["_query_since"](table, "message", 100, ("timestamp", "role")) == [{"timestamp": 100}, {"timestamp": 200}]
    for call in table.query.call_args_list:
        assert call.kwargs["ExpressionAttributeNames"] == {"#field0": "timestamp", "#field1": "role"}
        assert call.kwargs["ProjectionExpression"] == "#field0, #field1"
    assert table.query.call_args.kwargs["ExclusiveStartKey"] == {"pk": "next"}


def test_failed_history_read_is_retried():
    scope = tracking_scope()
    scope["calls_table"].query.side_effect = [RuntimeError("unavailable"), {"Items": []}]
    try:
        scope["_followup_call_tracking"]()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected the failed lookup to propagate")
    assert scope["_followup_call_tracking"]() == (None, [])
    assert scope["calls_table"].query.call_count == 2


@pytest.mark.parametrize("model", [Lead, MessageState, MissedCallState])
def test_queue_columns_exclude_large_fields_without_extra_queries(model):
    source = Path(__file__).resolve().parents[2] / "backend/routes/unanswered_messages.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_queue_lead_options"]
    scope = dict(Load=Load, joinedload=joinedload, Lead=Lead, Company=Company, User=User)
    exec(compile(tree, str(source), "exec"), scope)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add(Company(id="company", name="Movers", logo="large-logo", phone="2125550100"))
        db.add(User(id="rep", name="Rep", email="rep@example.com", password_hash="private"))
        db.add(Lead(id="lead", full_name="Client", phone="2125550200", notes="large-notes", company_id="company", assigned_to="rep"))
        db.add(MessageState(channel="sms", message_id="message", lead_id="lead", client_identifier="client", company_identifier="company", direction="inbound", occurred_at=now))
        db.add(MissedCallState(client_identifier="client", company_identifier="company", call_id="call", lead_id="lead", first_missed_at=now, latest_missed_at=now))
        db.commit()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    with Session(engine) as db:
        options = scope["_queue_lead_options"](None if model is Lead else model.lead)
        row = db.query(model).options(*options).one()
        lead = row if model is Lead else row.lead
        assert lead.full_name == "Client"
        assert lead.company.name == "Movers"
        assert lead.assignee.name == "Rep"
        for field in ("phone", "status", "priority", "created_at", "created_time", "facebook_user_id"):
            getattr(lead, field)
        for field in ("phone", "timezone", "aircall_number_id", "facebook_page_id"):
            getattr(lead.company, field)
        for field in ("phone", "aircall_number_id"):
            getattr(lead.assignee, field)
        assert "notes" in inspect(lead).unloaded
        assert "logo" in inspect(lead.company).unloaded
        assert "password_hash" in inspect(lead.assignee).unloaded
        assert len(statements) == 1
    engine.dispose()
