"""Exercise conversation persistence and upload batching without external services."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


@pytest.fixture
def api():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/liveswitch.py'
    tree = ast.parse(source.read_text())
    names = {'ensure_conversation', 'upload_urls'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in functions:
        node.decorator_list = []
        node.returns = None
        node.args.defaults = []
        for arg in node.args.args:
            arg.annotation = None
    lead = SimpleNamespace(id='lead-1', smartmoving_id='sm-1', phone=' 1112223333 ', company=SimpleNamespace(phone=' 2405707987 '))
    scope = {'get_opportunity': MagicMock(return_value={'data': {'quoteNumber': 23985}}), 'json': json, 'HTTPException': HTTPException, 'Lead': SimpleNamespace(id='id'),
             'LeadLiveSwitch': MagicMock(), '_get_visible_lead_or_404': MagicMock(return_value=lead),
             '_ensure_not_dispatch_write': MagicMock(), '_api_post': MagicMock()}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def test_reuses_conversation_without_api_call(api):
    db = MagicMock()
    db.get.return_value = SimpleNamespace(details=json.dumps({'id': 'saved', 'hostJoinUrl': 'host'}))
    assert api['ensure_conversation']('lead-1', object(), db)['id'] == 'saved'
    api['_api_post'].assert_not_called()


def test_creates_and_saves_all_links(api):
    db = MagicMock(); db.get.return_value = None
    details = dict(id='new', hostJoinUrl='host', participantJoinUrl='guest', conversationUrl='page', embeddedConversationUrl='embed')
    api['_api_post'].return_value = details
    assert api['ensure_conversation']('lead-1', object(), db) == {**details, 'name': '23985'}
    assert json.loads(api['LeadLiveSwitch'].call_args.kwargs['details']) == {**details, 'name': '23985'}
    assert api['_api_post'].call_args.args[1]['name'] == '23985'
    assert api['_api_post'].call_args.args[1]['phone'] == '2405707987'
    db.commit.assert_called_once()


def test_batches_files_in_one_request(api):
    db = MagicMock(); db.get.return_value = SimpleNamespace(details='{"id":"saved"}')
    files = [SimpleNamespace(contentType='image/jpeg', model_dump=lambda i=i: {'fileName': f'{i}.jpeg', 'contentType': 'image/jpeg'}) for i in range(20)]
    api['upload_urls']('lead-1', 'images', files, object(), db)
    api['_api_post'].assert_called_once()
    assert len(api['_api_post'].call_args.args[1]) == 20


def test_rejects_oversized_batch(api):
    db = MagicMock(); db.get.return_value = SimpleNamespace(details='{"id":"saved"}')
    with pytest.raises(HTTPException) as exc:
        api['upload_urls']('lead-1', 'images', [object()] * 21, object(), db)
    assert exc.value.status_code == 400
    api['_api_post'].assert_not_called()


def test_visibility_checked_before_accessing_conversation(api):
    db = MagicMock()
    api['_get_visible_lead_or_404'].side_effect = HTTPException(404, 'Lead not found')
    with pytest.raises(HTTPException):
        api['ensure_conversation']('other-lead', object(), db)
    db.get.assert_not_called()
    api['_api_post'].assert_not_called()


def test_missing_company_phone_never_uses_customer_phone(api):
    db = MagicMock(); db.get.return_value = None
    api['_get_visible_lead_or_404'].return_value.company.phone = ''
    with pytest.raises(HTTPException) as exc:
        api['ensure_conversation']('lead-1', object(), db)
    assert exc.value.status_code == 400
    api['_api_post'].assert_not_called()


def test_missing_quote_number_does_not_create_conversation(api):
    db = MagicMock(); db.get.return_value = None
    api['get_opportunity'].return_value = {'data': {}}
    with pytest.raises(HTTPException) as exc:
        api['ensure_conversation']('lead-1', object(), db)
    assert exc.value.status_code == 400
    api['_api_post'].assert_not_called()
