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
        node.args.defaults = node.args.defaults[-1:] if node.name == 'apply_spark_results_to_lead' else []
        for arg in node.args.args:
            arg.annotation = None
    lead = SimpleNamespace(id='lead-1', smartmoving_id='sm-1', quote_number=None, phone=' 1112223333 ', assignee=None, company=SimpleNamespace(phone=' 2405707987 ', aircall_number_id='company-number'))
    scope = {'get_opportunity': MagicMock(return_value={'data': {'quoteNumber': 23985}}), 'json': json, 'HTTPException': HTTPException, 'Lead': SimpleNamespace(id='id'),
             'Company': MagicMock(), 'PublicMoveAccess': MagicMock(), 'LeadLiveSwitch': MagicMock(), '_get_visible_lead_or_404': MagicMock(return_value=lead),
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


def test_unassigned_public_lead_uses_default_company_without_assignment(api):
    db = MagicMock(); db.get.return_value = None
    lead = api['_get_visible_lead_or_404'].return_value
    lead.company = None; lead.company_id = None
    lead.full_name = 'Jane Smith'; lead.quote_number = None; lead.smartmoving_id = None
    db.query.return_value.filter.return_value.one_or_none.return_value = SimpleNamespace(phone=' 2405707987 ')
    db.query.return_value.filter_by.return_value.first.return_value = object()
    api['_api_post'].return_value = {'id': 'new'}
    api['ensure_conversation']('lead-1', object(), db)
    assert api['_api_post'].call_args.args[1] == {'type':'LiveConversation','phone':'2405707987','name':'Jane Smith'}
    assert lead.company_id is None
    assert lead.company is None
    assert lead.quote_number is None
    api['get_opportunity'].assert_not_called()


def test_unassigned_lead_without_default_company_has_clear_error(api):
    db = MagicMock(); db.get.return_value = None
    api['_get_visible_lead_or_404'].return_value.company = None
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    with pytest.raises(HTTPException) as error:
        api['ensure_conversation']('lead-1', object(), db)
    assert 'default company' in error.value.detail
    api['_api_post'].assert_not_called()


def test_accepts_other_document_types(api):
    db = MagicMock()
    db.get.return_value = SimpleNamespace(details='{"id":"saved"}')
    file = SimpleNamespace(contentType='application/zip', model_dump=lambda: {'fileName': 'files.zip', 'contentType': 'application/zip'})
    api['upload_urls']('lead-1', 'documents', [file], object(), db)
    assert api['_api_post'].call_args.args[1][0]['contentType'] == 'application/zip'


def test_panel_prepare_accepts_large_video_without_proxying_bytes():
    from pydantic import BaseModel, Field
    source = Path(__file__).resolve().parents[2] / 'backend/routes/liveswitch.py'
    tree = ast.parse(source.read_text())
    nodes = [node for node in tree.body if getattr(node, 'name', '') in {'PanelUpload', 'prepare_panel_upload'}]
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
            node.args.defaults = []
            for arg in node.args.args:
                arg.annotation = None
    s3 = MagicMock()
    scope = {'BaseModel': BaseModel, 'Field': Field, 'boto3': SimpleNamespace(client=lambda _: s3),
        'panel_upload_context': MagicMock(return_value=(object(), None, 'bucket', 'scoped/key', 'video.mov'))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    body = scope['PanelUpload'](request_id='12345678-1234-1234-1234-123456789012', name='video.mov', size=3*1024*1024*1024)
    assert not scope['prepare_panel_upload']('lead', body, object(), MagicMock())['completed']
    assert ['content-length-range', 1, body.size] in s3.generate_presigned_post.call_args.kwargs['Conditions']


@pytest.fixture
def reports():
    import time
    from decimal import Decimal
    from datetime import datetime
    source = Path(__file__).resolve().parents[2] / 'backend/routes/liveswitch.py'
    names = {'trigger_lead_spark', 'apply_spark_results_to_lead', 'get_lead_spark_status'}
    functions = [n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name in names]
    for node in functions:
        node.decorator_list = []
        node.returns = None
        node.args.defaults = node.args.defaults[-1:] if node.name == 'apply_spark_results_to_lead' else []
        for arg in node.args.args: arg.annotation = None
    import sys
    sys.path.insert(0, str(source.parents[1]))
    from spark_history import remember_report
    scope = {'remember_report': remember_report, 'PublicMoveAccess': MagicMock(), 'SparkProcessingLog': MagicMock(), 'json': json, 'time': time, 'Decimal': Decimal, 'datetime': datetime, 'HTTPException': HTTPException,
             'LeadLiveSwitch': object(), 'Lead': object(), '_connection_config': lambda: {'spark_template_id': 'template'},
             '_api_post': MagicMock(return_value={'id': 'new-report', 'status': 'queued'}),
             '_api_get': MagicMock(return_value={'id': 'new-report', 'status': 'completed', 'shareUrl': 'new-url'}),
             '_ensure_not_dispatch_write': MagicMock(), '_get_visible_lead_or_404': MagicMock(return_value=SimpleNamespace(id='lead')),
             'fetch_and_extract_spark_report': MagicMock(return_value=(1200, 8400, []))}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def test_new_report_clears_old_extracted_values_and_link(reports):
    saved = SimpleNamespace(details=json.dumps({'id': 'conversation', 'last_spark_id': 'old',
        'spark_extracted_id': 'old', 'spark_extracted_cuft': 86.3, 'spark_extracted_weight': 604, 'last_spark_share_url': 'old-url', 'spark_processing': {'report_id': 'old'}}))
    db = MagicMock(); db.get.return_value = saved
    reports['trigger_lead_spark']('lead', None, db)
    data = json.loads(saved.details)
    assert data['last_spark_id'] == 'new-report'
    assert data['id'] == 'conversation'
    assert len(data['spark_history']) == 2
    assert data['spark_history'][0]['last_spark_share_url'] == 'old-url'
    assert data['spark_history'][1]['last_spark_id'] == 'new-report'
    assert all(key not in data for key in ('spark_extracted_id', 'spark_extracted_cuft', 'spark_extracted_weight', 'last_spark_share_url', 'spark_processing'))


def test_latest_completed_report_replaces_old_cuft_in_same_status_response(reports):
    saved = SimpleNamespace(details=json.dumps({'last_spark_id': 'new-report', 'spark_extracted_id': 'old-report', 'spark_extracted_cuft': 86.3}))
    db = MagicMock(); db.get.return_value = saved
    def apply(*args):
        data = json.loads(saved.details)
        data.update(spark_extracted_id='new-report', spark_extracted_cuft=1200, spark_extracted_weight=8400)
        saved.details = json.dumps(data)
    reports['apply_spark_results_to_lead'] = MagicMock(side_effect=apply)
    result = reports['get_lead_spark_status']('lead', object(), db)
    assert result['cuft'] == 1200
    reports['apply_spark_results_to_lead'].assert_called_once_with('lead', 'new-url', db)
    reports['get_lead_spark_status']('lead', object(), db)
    assert reports['apply_spark_results_to_lead'].call_count == 1


def test_apply_latest_report_reads_volume_again_and_reprices(reports):
    import sys
    from unittest.mock import patch
    lead = SimpleNamespace(id='lead', volume=86.3, weight=604)
    saved = SimpleNamespace(details=json.dumps({'last_spark_id': 'new-report', 'spark_extracted_cuft': 86.3}))
    job = SimpleNamespace(id='job', job_order=1, price=699)
    access = SimpleNamespace()
    db = MagicMock(); db.get.side_effect = [lead, saved]
    db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = job
    db.query.return_value.filter_by.return_value.first.return_value = access
    def recalculate(current_lead, current_job, session):
        assert current_lead.volume == 1200
        current_job.price = 2000
        return 2000
    calc = MagicMock(side_effect=recalculate)
    with patch.dict(sys.modules, {'models': MagicMock(), 'routes.pricing': SimpleNamespace(calculate_and_save_lead_job_price=calc)}):
        result = reports['apply_spark_results_to_lead']('lead', 'new-url', db)
    reports['fetch_and_extract_spark_report'].assert_called_once_with('new-url', processing=reports['SparkProcessingLog'].return_value)
    assert result['cuft'] == access.published_cuft == 1200
    assert result['price'] == access.published_price == 2000
    assert json.loads(saved.details)['spark_extracted_id'] == 'new-report'
    calc.assert_called_once()
