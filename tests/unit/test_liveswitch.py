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
    names = {'ensure_conversation', 'upload_urls', 'send_participant_sms'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in functions:
        node.decorator_list = []
        node.returns = None
        node.args.defaults = []
        for arg in node.args.args:
            arg.annotation = None
    lead = SimpleNamespace(id='lead-1', smartmoving_id='sm-1', quote_number=None, phone=' 1112223333 ', assignee=None, company=SimpleNamespace(phone=' 2405707987 ', aircall_number_id='company-number'))
    scope = {'get_opportunity': MagicMock(return_value={'data': {'quoteNumber': 23985}}), 'json': json, 'HTTPException': HTTPException, 'Lead': SimpleNamespace(id='id'),
             'PublicMoveAccess': MagicMock(), 'LeadLiveSwitch': MagicMock(), '_get_visible_lead_or_404': MagicMock(return_value=lead),
             '_ensure_not_dispatch_write': MagicMock(), '_api_post': MagicMock(),
             'SalesRep': SimpleNamespace(name='name'), 'func': MagicMock(),
             'send_sms': MagicMock(return_value={'ok': True, 'message_id': 'sms-1'}),
             'find_number_id': MagicMock(return_value=None)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def test_reuses_conversation_without_api_call(api):
    db = MagicMock()
    db.get.return_value = SimpleNamespace(details=json.dumps({'id': 'saved', 'hostJoinUrl': 'host'}))
    assert api['ensure_conversation']('lead-1', object(), db)['id'] == 'saved'
    api['_api_post'].assert_not_called()
    api['get_opportunity'].assert_not_called()


def test_creates_and_saves_all_links(api):
    db = MagicMock(); db.get.return_value = None; db.query.return_value.filter_by.return_value.first.return_value = None
    details = dict(id='new', hostJoinUrl='host', participantJoinUrl='guest', conversationUrl='page', embeddedConversationUrl='embed')
    api['_api_post'].return_value = details
    assert api['ensure_conversation']('lead-1', object(), db) == {**details, 'name': '23985'}
    assert json.loads(api['LeadLiveSwitch'].call_args.kwargs['details']) == {**details, 'name': '23985'}
    assert api['_api_post'].call_args.args[1]['name'] == '23985'
    assert api['_api_post'].call_args.args[1]['phone'] == '2405707987'
    api['get_opportunity'].assert_called_once_with('sm-1')
    assert api['_get_visible_lead_or_404'].return_value.quote_number == '23985'
    db.commit.assert_called_once()


@pytest.mark.parametrize('smartmoving_id', ['sm-1', None])
def test_uses_stored_quote_without_smartmoving_request(api, smartmoving_id):
    db = MagicMock(); db.get.return_value = None; db.query.return_value.filter_by.return_value.first.return_value = None
    lead = api['_get_visible_lead_or_404'].return_value
    lead.quote_number = '12345'
    lead.smartmoving_id = smartmoving_id
    api['_api_post'].return_value = {'id': 'new'}
    result = api['ensure_conversation']('lead-1', object(), db)
    assert result['name'] == '12345'
    assert api['_api_post'].call_args.args[1]['name'] == '12345'
    assert lead.quote_number == '12345'
    api['get_opportunity'].assert_not_called()
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
    db = MagicMock(); db.get.return_value = None; db.query.return_value.filter_by.return_value.first.return_value = None
    api['_get_visible_lead_or_404'].return_value.company.phone = ''
    with pytest.raises(HTTPException) as exc:
        api['ensure_conversation']('lead-1', object(), db)
    assert exc.value.status_code == 400
    api['_api_post'].assert_not_called()


def test_missing_quote_number_does_not_create_conversation(api):
    db = MagicMock(); db.get.return_value = None; db.query.return_value.filter_by.return_value.first.return_value = None
    api['get_opportunity'].return_value = {'data': {}}
    with pytest.raises(HTTPException) as exc:
        api['ensure_conversation']('lead-1', object(), db)
    assert exc.value.status_code == 400
    api['_api_post'].assert_not_called()


@pytest.mark.parametrize('sender', ['assigned-rep', 'sales-reps-table', 'company', 'company-no-rep-match', 'company-phone'])
def test_participant_sms_uses_correct_sender_and_saved_link(api, sender):
    db = MagicMock()
    link = 'https://api.production.liveswitch.com/contact/s/test-link'
    db.get.return_value = SimpleNamespace(details=json.dumps({'participantJoinUrl': link}))
    db.query.return_value.filter.return_value.first.return_value = None
    lead = api['_get_visible_lead_or_404'].return_value
    expected_number = 'company-number'
    if sender in ('assigned-rep', 'sales-reps-table', 'company-no-rep-match'):
        lead.assignee = SimpleNamespace(name=' Eli Jones ', aircall_number_id=None)
    if sender == 'assigned-rep':
        lead.assignee.aircall_number_id = 'rep-number'
        expected_number = 'rep-number'
    elif sender == 'sales-reps-table':
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(aircall_number_id='mapped-rep-number')
        expected_number = 'mapped-rep-number'
    elif sender == 'company-phone':
        lead.company.aircall_number_id = None
        api['find_number_id'].return_value = 'resolved-company-number'
        expected_number = 'resolved-company-number'
    assert api['send_participant_sms']('lead-1', object(), db) == {'ok': True, 'message_id': 'sms-1'}
    api['send_sms'].assert_called_once_with(
        to='1112223333', text=f'Please click this link to join the live video call. {link}', number_id=expected_number,
    )
    api['get_opportunity'].assert_not_called()
    api['_api_post'].assert_not_called()
    if sender == 'sales-reps-table':
        api['func'].trim.assert_called_once_with(api['SalesRep'].name)
        api['func'].lower.return_value.__eq__.assert_called_once_with('eli jones')
    if sender == 'company-phone':
        api['find_number_id'].assert_called_once_with(lead.company.phone)
    else:
        api['find_number_id'].assert_not_called()


@pytest.mark.parametrize('missing,status', [('conversation', 409), ('link', 400), ('phone', 400), ('sender', 400), ('access', 404), ('permission', 403)])
def test_participant_sms_rejects_missing_data_or_access(api, missing, status):
    db = MagicMock()
    db.get.return_value = SimpleNamespace(details='{"participantJoinUrl":"https://example.com/join"}')
    lead = api['_get_visible_lead_or_404'].return_value
    if missing == 'conversation':
        db.get.return_value = None
    elif missing == 'link':
        db.get.return_value.details = '{}'
    elif missing == 'phone':
        lead.phone = ''
    elif missing == 'sender':
        lead.company.aircall_number_id = ''
    elif missing == 'access':
        api['_get_visible_lead_or_404'].side_effect = HTTPException(404, 'Lead not found')
    elif missing == 'permission':
        api['_ensure_not_dispatch_write'].side_effect = HTTPException(403, 'Not allowed')
    with pytest.raises(HTTPException) as exc:
        api['send_participant_sms']('lead-1', object(), db)
    assert exc.value.status_code == status
    api['send_sms'].assert_not_called()


def test_participant_sms_returns_aircall_error(api):
    db = MagicMock()
    db.get.return_value = SimpleNamespace(details='{"participantJoinUrl":"https://example.com/join"}')
    api['send_sms'].return_value = {'ok': False, 'detail': 'SMS not enabled for this number'}
    with pytest.raises(HTTPException) as exc:
        api['send_participant_sms']('lead-1', object(), db)
    assert exc.value.status_code == 502
    assert exc.value.detail == 'SMS not enabled for this number'


def test_configured_bearer_token_does_not_require_oauth():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/liveswitch.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_access_token')
    settings = MagicMock(side_effect=AssertionError('OAuth should not be required'))
    scope = {'get_config': lambda: {'LIVESWITCH_ACCESS_TOKEN': 'test-token'}, '_settings': settings}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    assert scope['_access_token']() == 'test-token'
    settings.assert_not_called()


def test_public_intake_uses_customer_name_without_smartmoving(api):
    db = MagicMock(); db.get.return_value = None
    lead = api['_get_visible_lead_or_404'].return_value
    lead.full_name = 'Jane Smith'; lead.quote_number = None; lead.smartmoving_id = None
    db.query.return_value.filter_by.return_value.first.return_value = object()
    api['_api_post'].return_value = {'id': 'new'}
    assert api['ensure_conversation']('lead-1', object(), db)['name'] == 'Jane Smith'
    api['get_opportunity'].assert_not_called()
    assert lead.quote_number is None
