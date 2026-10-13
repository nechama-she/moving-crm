import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from report_conversation import prepare_upload_conversation


@pytest.mark.parametrize('used', [False, True])
def test_session_is_reused_until_report_runs(monkeypatch, used):
    state = {'id': 'current', 'spark_history': []}
    if used:
        state['spark_history'] = [{'last_spark_id': 'report', 'report_conversation': {'id': 'current'}}]
    saved = SimpleNamespace(details=json.dumps(state))
    row = SimpleNamespace(synced_at='done', sync_status='synced', sync_token='token', sync_upload_url=None, sync_error=None)
    db = MagicMock()
    db.get.return_value = saved
    db.query.return_value.filter_by.return_value.all.return_value = [row]
    ensure = MagicMock(return_value={'id': 'new' if used else 'current'})
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', SimpleNamespace(ensure_lead_conversation=ensure))
    result = prepare_upload_conversation(SimpleNamespace(lead_id='lead', id='access'), db)
    assert ensure.call_args.kwargs['fresh'] is used
    assert result['id'] == ('new' if used else 'current')
    assert row.synced_at == (None if used else 'done')
    assert row.sync_status == ('pending' if used else 'synced')
    if used:
        # The newly created conversation does not need replacing a second time.
        from report_conversation import conversation_has_report
        assert not conversation_has_report(json.loads(saved.details))
