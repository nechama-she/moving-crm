"""Queue history performance regressions, without AWS credentials or network."""
import ast
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from unittest.mock import Mock
import sys

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Load, Session, joinedload

from boto3.dynamodb.conditions import Key

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from models import Base, Company, Lead, MessageState, MissedCallState, User
from work_queue_rules import _digits, _epoch


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
