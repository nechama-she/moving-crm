import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from message_state_cleanup import latest_message


def message(timestamp, role="user", **extra):
    return {"timestamp": timestamp, "role": role, "platform": "messenger", "page_id": "page", **extra}


def test_checks_later_pages_for_reply_without_message_id():
    table = Mock()
    table.query.side_effect = [
        {"Items": [message(1700000000)], "LastEvaluatedKey": {"user_id": "client", "timestamp": 1700000000}},
        {"Items": [message(1700000010000, "agent")]},
    ]
    latest = latest_message(table, "messenger", "client", "page")
    assert latest[1] == "outbound"
    assert latest[0].timestamp() == 1700000010
    assert "ExclusiveStartKey" in table.query.call_args.kwargs
    assert table.query.call_args.kwargs["ConsistentRead"]


def test_latest_customer_message_wins_over_older_reply():
    table = Mock()
    table.query.return_value = {"Items": [message(100, "agent"), message(200)]}
    assert latest_message(table, "messenger", "client", "page")[1] == "inbound"


def test_other_page_and_ai_do_not_resolve_conversation():
    table = Mock()
    table.query.return_value = {"Items": [message(100), message(200, "ai"), message(300, "agent", page_id="other")]}
    assert latest_message(table, "messenger", "client", "page")[1] == "inbound"


def test_sms_checks_phone_variants_and_company_number():
    table = Mock()
    table.query.return_value = {"Items": [
        {"timestamp": 100, "direction": "received", "company_number": "+12025550100"},
        {"timestamp": 200, "direction": "sent", "company_number": "2025550100"},
        {"timestamp": 300, "direction": "received", "company_number": "2025550199"},
    ]}
    assert latest_message(table, "sms", "2125550100", "2025550100")[1] == "outbound"
    assert table.query.call_count >= 3


def test_failed_page_cannot_return_partial_proof():
    table = Mock()
    table.query.side_effect = [
        {"Items": [message(200, "agent")], "LastEvaluatedKey": {"user_id": "client", "timestamp": 200}},
        RuntimeError("source unavailable"),
    ]
    with pytest.raises(RuntimeError):
        latest_message(table, "messenger", "client", "page")


def test_unknown_or_equal_time_message_is_not_proof_of_answer():
    table = Mock()
    table.query.return_value = {"Items": [message(100, "agent"), message(100)]}
    assert latest_message(table, "messenger", "client", "page")[1] == "inbound"
    table.query.return_value = {"Items": [message(100, "agent"), message(200, "unrecognized")]}
    assert latest_message(table, "messenger", "client", "page")[1] == "unknown"
