import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import inventory_ready_sms as sms
from models import LeadLiveSwitch, PublicMoveAccess


@pytest.mark.parametrize("environment,prefix,enabled", [
    ("dev", "/moving-crm/prod/", False),
    ("staging", "/moving-crm/prod/", False),
    ("prod", "/moving-crm/prod/", False),
    (None, "/moving-crm/dev/", False),
    (None, "/moving-crm/staging/", False),
    (None, "/moving-crm/prod/", False),
    (None, "", False),
])
def test_production_gate(monkeypatch, environment, prefix, enabled):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    if environment is not None:
        monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("SSM_PREFIX", prefix)
    assert sms.production_sms_enabled() is enabled
    if not enabled:
        db = MagicMock()
        sms.notify_inventory_ready("lead", "report", db)
        assert not db.mock_calls


@pytest.mark.parametrize("source,mime,completed,sends", [
    ("liveswitch", "video/mp4", True, False),
    ("combined", "video/quicktime", True, False),
    ("manual", "video/mp4", True, False),
    ("liveswitch", "image/jpeg", True, False),
    ("liveswitch", "video/mp4", False, False),
])
def test_completion_notice_never_sends_in_production(monkeypatch, source, mime, completed, sends):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    send = MagicMock(return_value={"ok": True})
    monkeypatch.setitem(sys.modules, "libs.aircall.client", SimpleNamespace(send_sms=send, find_number_id=MagicMock()))
    monkeypatch.setitem(sys.modules, "routes.public_moves", SimpleNamespace(public_url=lambda access: "https://customer.test/move/link"))
    saved = SimpleNamespace(details=json.dumps({
        "last_spark_id": "report", "spark_extracted_id": "report",
        "last_spark_status": "completed" if completed else "running",
        "report_source": source, "report_files": [{"content_type": mime}],
    }))
    lead = SimpleNamespace(phone="+12025550111", company=SimpleNamespace(aircall_number_id="sender"))
    db = MagicMock()
    report_query = MagicMock()
    report_query.filter_by.return_value.populate_existing.return_value.with_for_update.return_value.first.return_value = saved
    access_query = MagicMock()
    access_query.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(id="access")
    db.query.side_effect = lambda model: report_query if model is LeadLiveSwitch else access_query
    db.get.return_value = lead
    sms.notify_inventory_ready("lead", "report", db)
    sms.notify_inventory_ready("lead", "report", db)
    assert send.call_count == int(sends)
    assert not db.mock_calls
