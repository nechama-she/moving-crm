import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from boto3.dynamodb.types import TypeSerializer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import message_stream_handler


def record(item):
    image = {key: TypeSerializer().serialize(value) for key, value in item.items()}
    return {
        "eventName": "INSERT",
        "eventSourceARN": "arn:aws:dynamodb:us-east-1:1:table/conversations/stream/2026",
        "dynamodb": {"NewImage": image, "SequenceNumber": "1"},
    }


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_website_chat_bot_messages_never_become_message_state(role):
    db = Mock()
    item = {"user_id": "web-abc123", "message_id": "m-1", "timestamp": 1777000000000, "text": "Hi",
            "platform": "website_gorillah_bot", "page_id": "gorillahaulers.com", "role": role,
            "record_type": "message", "lead_id": "lead-7"}

    assert message_stream_handler._process_record(db, record(item), "1") == (False, None)
    db.execute.assert_not_called()
    db.query.assert_not_called()
