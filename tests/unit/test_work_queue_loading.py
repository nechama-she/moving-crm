"""Saved queue state and task lifecycle regressions, without AWS or network."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace
import sys

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Load, Session, joinedload

from boto3.dynamodb.conditions import Key

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from models import Base, Company, Lead, MessageState, MissedCallState, User, FirstContactState
from work_queue_rules import _epoch


def test_creation_loads_smartmoving_details_before_tasks():
    from fastapi import HTTPException
    from pydantic import BaseModel, ConfigDict, Field

    class Input(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        smartmoving_id: str | None = None
        priority: int = 0
        full_name: str = 'Push name'
        quote_number: str | None = Field(default=None, alias='quoteNumber')

    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == '_hydrate_new_lead_from_smartmoving')
    fetch = Mock(return_value={'data': {'id': 'sm-1'}})
    mapping = Mock(return_value={'priority': 2, 'full_name': 'Saved name', 'quote_number': '27210'})
    scope = dict(NewLead=Input, HTTPException=HTTPException, User=SimpleNamespace,
                 logger=Mock(),
                 _clean_optional_text=lambda value: (value or '').strip(),
                 get_opportunity=fetch, _build_smartmoving_refresh_payload=mapping)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    hydrate = scope['_hydrate_new_lead_from_smartmoving']
    native = Input()
    assert hydrate(native) is native
    fetch.assert_not_called()
    result = hydrate(Input(smartmoving_id='sm-1'))
    fetch.assert_called_once_with('sm-1')
    assert (result.priority, result.full_name, result.quote_number) == (2, 'Saved name', '27210')
    submitted = Input(smartmoving_id='sm-1', priority=1, quoteNumber='original')
    mapping.return_value = {'full_name': 'Updated name'}
    result = hydrate(submitted)
    assert result.priority == 1
    assert result.full_name == 'Updated name'
    for response in ({'error': 'HTTP 400'}, {'error': 'Unavailable'}, {'data': None}):
        fetch.return_value = response
        assert hydrate(submitted) is submitted
    fetch.side_effect = TimeoutError('SmartMoving timeout')
    assert hydrate(submitted) is submitted
    fetch.side_effect = None
    fetch.return_value = {'data': {'id': 'sm-1'}}
    mapping.return_value = {'priority': 'invalid'}
    assert hydrate(submitted) is submitted

    creation = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_create_lead')
    hydrate_call = next(node for node in ast.walk(creation) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == '_hydrate_new_lead_from_smartmoving')
    lead_call = next(node for node in ast.walk(creation) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'Lead')
    assert hydrate_call.lineno < lead_call.lineno
    guard = next(node for node in creation.body if isinstance(node, ast.If)
                 and hydrate_call in list(ast.walk(node)))
    lookup = Mock(return_value='hydrated')
    guarded_scope = dict(created_in_smartmoving_here=True, body='copied',
                         _hydrate_new_lead_from_smartmoving=lookup)
    guarded_code = compile(ast.Module(body=[guard], type_ignores=[]), str(source), 'exec')
    exec(guarded_code, guarded_scope)
    lookup.assert_not_called()
    assert guarded_scope['body'] == 'copied'
    guarded_scope['created_in_smartmoving_here'] = False
    exec(guarded_code, guarded_scope)
    lookup.assert_called_once_with('copied')
    assert guarded_scope['body'] == 'hydrated'
    duplication = next(node for node in creation.body if isinstance(node, ast.If)
                       and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                               and call.func.id == '_enqueue_lead_for_duplication' for call in ast.walk(node)))
    suppression = next(node for node in creation.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'suppress_new_lead_automation' for target in node.targets))
    terminal = next(node for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'NO_MESSAGE_STATUSES' for target in node.targets))
    eligibility = compile(ast.Expression(duplication.test), str(source), 'eval')
    for status in ('new', 'contacted', 'quoted', 'booked', 'scheduled', 'completed', 'lost', 'cancelled'):
        for priority in (0, 1, 3):
            scope = dict(lead=SimpleNamespace(status=status, priority=priority, referral_source='Facebook'))
            exec(compile(ast.Module(body=[terminal, suppression], type_ignores=[]), str(source), 'exec'), scope)
            assert bool(eval(eligibility, scope)) == (status in ('new', 'contacted', 'quoted', 'lost', 'cancelled'))
            enqueue = next(node for node in ast.walk(duplication) if isinstance(node, ast.Call)
                           and isinstance(node.func, ast.Name) and node.func.id == '_enqueue_lead_for_duplication')
            approval = next(keyword.value for keyword in enqueue.keywords if keyword.arg == 'requires_approval')
            assert eval(compile(ast.Expression(approval), str(source), 'eval'), scope) == (status in ('lost', 'cancelled'))
    assert any(item.arg == 'priority' and isinstance(item.value, ast.Attribute)
               and item.value.attr == 'priority' for item in lead_call.keywords)


@pytest.mark.parametrize('status,expected', [(4, 'booked'), (20, 'cancelled'), (3, 'quoted')])
def test_followup_backfill_refreshes_remote_state_before_import(status, expected):
    from smartmoving_followup_backfill import refresh_one
    db = Mock()
    lead = SimpleNamespace(smartmoving_id='sm-1', priority=0, status='new')
    check = Mock(return_value={'ok': True, 'exists': True, 'status': status, 'lead_status': 'Priority 2'})
    def import_tasks(session, refreshed, *, commit):
        assert session is db
        assert (refreshed.priority, refreshed.status) == (2, expected)
        assert commit is False
        db.flush.assert_called_once()
        return 2
    assert refresh_one(db, lead, check, import_tasks) == 'imported:2'
    db.commit.assert_not_called()


def test_smartmoving_bulk_requests_honor_retry_after_and_reset(monkeypatch):
    import httpx
    from libs.smartmoving import client
    request = httpx.Request('GET', 'https://example.test/followups')
    limited = httpx.Response(429, headers={'Retry-After': '12'}, request=request)
    success = httpx.Response(200, request=request)
    send = Mock(side_effect=[limited, limited, success])
    sleep = Mock()
    monkeypatch.setattr(client.time, 'sleep', sleep)
    monkeypatch.setattr(client, '_log_http_request', Mock())
    with client.bulk_requests():
        assert client._request(send) is success
    assert [call.args[0] for call in sleep.call_args_list] == [1, 17, 1, 17, 1]
    assert client._BULK_REQUESTS.get() is False


def test_smartmoving_bulk_requests_follow_response_waits_beyond_six_attempts(monkeypatch):
    import httpx
    from libs.smartmoving import client
    request = httpx.Request('GET', 'https://example.test/followups')
    delays = [12, 25, 8, 60, 30, 90, 15]
    responses = [httpx.Response(429, json={'message': f'Try again in {delay} seconds'}, request=request) for delay in delays]
    send = Mock(side_effect=[*responses, httpx.Response(200, request=request)])
    sleep = Mock()
    monkeypatch.setattr(client.time, 'sleep', sleep)
    monkeypatch.setattr(client, '_log_http_request', Mock())
    with client.bulk_requests():
        assert client._request(send).status_code == 200
    assert send.call_count == 8
    assert [call.args[0] for call in sleep.call_args_list if call.args[0] != 1] == [delay + 5 for delay in delays]


@pytest.mark.parametrize('priority', [None, '', 0, '0'])
def test_followup_backfill_skips_tasks_for_remote_zero_or_unset(priority):
    from smartmoving_followup_backfill import refresh_one
    lead = SimpleNamespace(smartmoving_id='sm-1', priority=2, status='new')
    importer = Mock()
    check = Mock(return_value={'ok': True, 'exists': True, 'status': 20, 'lead_status': priority})
    assert refresh_one(Mock(), lead, check, importer) == 'skipped_priority_zero'
    assert (lead.priority, lead.status) == (0, 'cancelled')
    importer.assert_not_called()


@pytest.mark.parametrize('response', [{'ok': False}, {'ok': True, 'status': 999, 'lead_status': 2},
                                     {'ok': True, 'status': 4, 'lead_status': 'invalid'}])
def test_followup_backfill_does_not_import_on_refresh_failure(response):
    from smartmoving_followup_backfill import refresh_one
    lead = SimpleNamespace(smartmoving_id='sm-1', priority=2, status='new')
    importer = Mock()
    with pytest.raises(ValueError):
        refresh_one(Mock(), lead, Mock(return_value=response), importer)
    assert (lead.priority, lead.status) == (2, 'new')
    importer.assert_not_called()


@pytest.fixture
def task_queue(monkeypatch):
    import followup_tasks
    from models import Task
    monkeypatch.setattr('work_queue_rules._is_us_client_phone', lambda phone: True)
    replay = Mock(return_value=([], []))
    monkeypatch.setattr(followup_tasks, 'history', replay)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(id='company', name='Movers', phone='2029372625', timezone='America/New_York')
        lead = Lead(id='lead', full_name='Client', phone='2403703417', company=company,
                    created_at=datetime(2026, 10, 16, 13, tzinfo=timezone.utc), smartmoving_id='sm-1', created_time='2026-10-16T13:00:00Z', status='new')
        db.add(lead)
        db.commit()
        yield followup_tasks, db, lead, Task, replay
    engine.dispose()


@pytest.mark.parametrize('smartmoving_id', [None, 'sm-1'])
def test_tasks_use_saved_priority_for_every_lead(task_queue, smartmoving_id, monkeypatch):
    from contextlib import nullcontext
    service, db, lead, Task, _ = task_queue
    lead.smartmoving_id = smartmoving_id
    db.commit()
    monkeypatch.setitem(sys.modules, 'database', SimpleNamespace(SessionLocal=lambda: nullcontext(db)))
    monkeypatch.setitem(sys.modules, 'realtime', SimpleNamespace(publish_realtime_event=Mock()))
    service.sync_saved_lead(lead.id)
    assert db.query(Task).count() == 9


@pytest.fixture
def new_lead_payload_model():
    # Load the real request models without importing route-level AWS clients.
    from typing import Any
    from pydantic import BaseModel, ConfigDict, Field, field_validator
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'NewLead', 'LeadJobChargePayload', 'EstimatedTotalPayload',
             'LeadPaymentPayload', 'ExternalLeadUpdateLog',
             'ExternalLeadUpdateLogRequest', 'ExternalLeadUpdateLogResponse'}
    models = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    scope = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
                 field_validator=field_validator, Any=Any)
    exec(compile(ast.Module(body=models, type_ignores=[]), str(source), 'exec'), scope)
    return scope['NewLead']


@pytest.mark.parametrize('priority_fields,expected', [({}, 0), ({'priority': None}, 0),
                                                    ({'priority': 0}, 0), ({'priority': 2}, 2)])
def test_new_lead_priority_normalizes_before_persistence(task_queue, new_lead_payload_model,
                                                       priority_fields, expected):
    _, db, existing, _, _ = task_queue
    body = new_lead_payload_model.model_validate({
        'company_name': 'Movers', 'source': 'api', 'full_name': 'New client', **priority_fields})
    assert body.priority == expected
    # Use the same priority expression as the real creation handler.
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    creation = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_create_lead')
    constructor = next(node for node in ast.walk(creation) if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Name) and node.func.id == 'Lead')
    priority = next(keyword.value for keyword in constructor.keywords if keyword.arg == 'priority')
    saved = Lead(id='new-client', company_id=existing.company_id, full_name=body.full_name,
                 priority=eval(compile(ast.Expression(priority), str(source), 'eval'), {'body': body}))
    db.add(saved)
    db.commit()
    db.refresh(saved)
    assert saved.priority == expected


@pytest.mark.parametrize('priority', [-1, 'invalid'])
def test_new_lead_priority_still_rejects_invalid_values(new_lead_payload_model, priority):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        new_lead_payload_model.model_validate({'company_name': 'Movers', 'source': 'api', 'priority': priority})


@pytest.mark.parametrize('priority', [0, None])
def test_smartmoving_refresh_skips_followups_for_zero_and_unset(monkeypatch, priority):
    import smartmoving_followup_sync as service
    fetch = Mock()
    monkeypatch.setattr(service, 'get_followups', fetch)
    db = Mock()
    assert service.sync(db, SimpleNamespace(priority=priority, smartmoving_id='sm-1')) == 0
    fetch.assert_not_called()
    assert db.mock_calls == []


def test_smartmoving_refresh_upserts_remote_tasks(monkeypatch):
    from unittest.mock import MagicMock
    import smartmoving_followup_sync as service
    remote = {'id': 'followup-1', 'type': 1, 'title': 'Discuss estimate',
              'assignedToId': 'rep-1', 'dueDateTime': '2026-10-24T15:00:00Z',
              'notes': 'Call after lunch', 'completed': False}
    fetch = Mock(return_value={'data': [remote]})
    monkeypatch.setattr(service, 'get_followups', fetch)
    db = MagicMock()
    lead = SimpleNamespace(priority=1, smartmoving_id='sm-1')
    assert service.sync(db, lead) == 1
    fetch.assert_called_once_with('sm-1')
    statement, params = db.execute.call_args.args
    assert 'ON CONFLICT (lead_id, smartmoving_followup_id) DO UPDATE' in str(statement)
    assert 'l.priority IS NOT NULL AND l.priority <> 0' in str(statement)
    assert params['note_id'] == 'followup-1'
    assert params['title'] == 'Discuss estimate'
    assert params['due_date_time_iso'] == remote['dueDateTime']
    assert params['notes'] == 'Call after lunch'
    assert params['completed'] is False
    remote['completed'] = True
    service.sync(db, lead)
    assert db.execute.call_args.args[1]['note_id'] == 'followup-1'
    assert db.execute.call_args.args[1]['completed'] is True
    assert db.commit.call_count == 2


@pytest.mark.parametrize('response', [{'error': 'HTTP 503'}, {'data': {}},
                                     {'data': [{'id': 'bad'}]}])
def test_smartmoving_refresh_failure_does_not_write_tasks(monkeypatch, response):
    import smartmoving_followup_sync as service
    monkeypatch.setattr(service, 'get_followups', Mock(return_value=response))
    db = Mock()
    with pytest.raises(ValueError, match='SmartMoving follow-up refresh'):
        service.sync(db, SimpleNamespace(priority=2, smartmoving_id='sm-1'))
    assert db.mock_calls == []



@pytest.mark.parametrize('already_initialized', [False, True])
def test_existing_communications_complete_initial_and_reconciled_tasks(task_queue, already_initialized):
    service, db, lead, Task, replay = task_queue
    if already_initialized:
        service.sync(db, lead)
        db.commit()
    call_time = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
    rep = User(id='rep', name='Rep', email='rep@example.com', password_hash='unused', phone='4439513493')
    db.add(rep)
    lead.assignee = rep
    call = {'timestamp': call_time.timestamp(), 'phone_number': lead.phone, 'company_number': rep.phone}
    replay.return_value = ([call, call], [{'channel': 'sms', 'client': lead.phone,
                                          'destination': rep.phone, 'occurred_at': call_time}])
    service.sync(db, lead, reconcile=already_initialized)
    db.commit()
    assert db.query(Task).count() == 9
    assert db.query(Task).filter_by(task_type='call', status='done').count() == 1
    assert db.query(Task).filter_by(task_type='text', status='done').count() == 1
    completed = db.query(Task).filter_by(task_type='call', status='done').one()
    assert service.utc(completed.completed_at) == call_time
    service.sync(db, lead, reconcile=True)
    db.commit()
    assert db.query(Task).count() == 9
    assert db.query(Task).filter_by(task_type='call', status='done').count() == 1


def test_nonzero_priority_never_creates_tasks_or_reads_history(task_queue):
    service, db, lead, Task, replay = task_queue
    lead.priority = 2
    service.sync(db, lead)
    db.commit()
    assert db.query(Task).count() == 0
    assert lead.priority == 2
    replay.assert_not_called()


def test_tasks_do_not_require_smartmoving_creation_time(task_queue):
    service, db, lead, Task, _ = task_queue
    lead.created_time = ''
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    assert db.query(Task).count() == 9


def test_reconciliation_updates_existing_task_titles(task_queue):
    service, db, lead, Task, _ = task_queue
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    morning = db.query(Task).filter_by(automatic_key='priority0:call:1').one()
    morning.title = 'Evening call'
    db.commit()
    service.sync(db, lead, reconcile=True)
    db.commit()
    assert morning.title == 'Morning call'
    assert service.utc(morning.due_at) == datetime(2026, 10, 16, 16, tzinfo=timezone.utc)
    assert db.query(Task).count() == 9


@pytest.mark.parametrize('smartmoving_time,source', [
    ('2026-10-16T12:00:00Z', 'smartmoving'),
    ('2026-10-16T14:00:00Z', 'crm'),
])
def test_followups_use_earlier_creation_time(task_queue, smartmoving_time, source):
    service, db, lead, Task, _ = task_queue
    lead.created_time = smartmoving_time
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    call_time = datetime(2026, 10, 16, 12, 47, tzinfo=timezone.utc)
    service.record_contact(db, lead, 'calls', {
        'phone_number': lead.phone, 'company_number': lead.company.phone,
        'direction': 'outbound', 'timestamp': call_time.timestamp(),
    })
    db.commit()
    tasks = db.query(Task).all()
    morning = next(task for task in tasks if task.automatic_key == 'priority0:call:1')
    assert morning.status == ('done' if source == 'smartmoving' else 'open')
    row = service.lead_row(lead, tasks, datetime.now(timezone.utc))
    assert row['created_time_source'] == source
    expected_hour = 12 if source == 'smartmoving' else 13
    assert datetime.fromisoformat(row['created_at']).hour == expected_hour


def test_late_message_delivery_can_correct_an_earlier_superseded_task(task_queue):
    service, db, lead, Task, _ = task_queue
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    sms = {'phone_number': lead.phone, 'company_number': lead.company.phone, 'direction': 'sent', 'sales_name': 'Rep'}
    service.record_contact(db, lead, 'sms', {**sms, 'timestamp': datetime(2026, 10, 17, 14, tzinfo=timezone.utc).timestamp()})
    db.commit()
    welcome = db.query(Task).filter_by(automatic_key='priority0:message:1').one()
    assert welcome.completion_reason == 'Superseded by later message'
    service.record_contact(db, lead, 'sms', {**sms, 'timestamp': datetime(2026, 10, 16, 14, tzinfo=timezone.utc).timestamp()})
    db.commit()
    assert welcome.completion_reason == 'Communication'
    assert db.query(Task).filter(Task.completed_at.isnot(None), Task.task_type == 'text').count() == 2


def test_confirmed_zero_creates_nine_timed_tasks_once_and_priority_change_closes_them(task_queue):
    service, db, lead, Task, replay = task_queue
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    tasks = db.query(Task).all()
    assert len(tasks) == 9
    assert sum(task.task_type == 'call' for task in tasks) == 6
    assert sum(task.task_type == 'text' for task in tasks) == 3
    assert all(task.due_at and task.scheduled_start and task.status == 'open' for task in tasks)
    assert min(service.utc(task.due_at) for task in tasks) == datetime(2026, 10, 16, 16, tzinfo=timezone.utc)
    welcome = next(task for task in tasks if task.automatic_key == 'priority0:message:1')
    # 8 PM Eastern is midnight UTC the next day; Activity retains the local date.
    assert service.utc(welcome.due_at) == datetime(2026, 10, 17, 0, tzinfo=timezone.utc)
    assert welcome.due_date == '2026-10-16'
    morning = next(task for task in tasks if task.automatic_key == 'priority0:call:1')
    assert service.utc(morning.scheduled_start) == datetime(2026, 10, 16, 13, tzinfo=timezone.utc)
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    assert db.query(Task).count() == 9
    assert replay.call_count == 1
    lead.priority = 1
    service.sync(db, lead)
    db.commit()
    assert all(task.status == 'done' and task.completion_reason == 'Priority changed' for task in db.query(Task))
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    assert all(task.status == 'done' for task in db.query(Task))


def test_duplicate_calls_and_wrong_destination_do_not_complete_extra_tasks(task_queue):
    service, db, lead, Task, _ = task_queue
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    call = {'timestamp': datetime(2026, 10, 16, 14, tzinfo=timezone.utc).timestamp(),
            'phone_number': lead.phone, 'company_number': lead.company.phone, 'direction': 'outbound'}
    assert service.record_contact(db, lead, 'calls', call)
    db.commit()
    assert not service.record_contact(db, lead, 'calls', call)
    db.commit()
    assert db.query(Task).filter_by(status='done', task_type='call').count() == 1
    service.record_contact(db, lead, 'calls', {**call, 'timestamp': call['timestamp'] + 4 * 3600, 'company_number': '9999999999'})
    db.commit()
    assert db.query(Task).filter_by(status='done', task_type='call').count() == 1
    service.record_contact(db, lead, 'sms', {**call, 'sales_name': 'AI'})
    db.commit()
    assert db.query(Task).filter_by(status='done', task_type='text').count() == 0


def test_overdue_view_only_reads_saved_tasks_and_applies_filters_in_sql(task_queue, monkeypatch):
    service, db, lead, Task, replay = task_queue
    lead.priority = 0
    service.sync(db, lead)
    db.commit()
    for task in db.query(Task):
        task.scheduled_start = datetime.now(timezone.utc) - timedelta(hours=2)
        task.due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    replay.reset_mock()
    source = Path(__file__).resolve().parents[2] / 'backend/routes/unanswered_messages.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'list_followup_calls', '_queue_lead_options', '_open_sales_status_filter', '_exclude_mirit_company_filter', '_with_smartmoving_links'}]
    for node in tree.body:
        node.decorator_list = []
        if node.name == 'list_followup_calls':
            node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    ast.fix_missing_locations(tree)
    from sqlalchemy import func, or_, and_, cast, String
    scope = dict(Lead=Lead, Company=Company, User=User, Session=Session, Load=Load, joinedload=joinedload,
                 datetime=datetime, timezone=timezone, func=func, or_=or_, and_=and_, cast=cast, String=String,
                 OPEN_SALES_STATUSES=('new', 'contacted', 'quoted'), MIRIT_COMPANY_NAME='mirit great american')
    exec(compile(tree, str(source), 'exec'), scope)
    kwargs = dict(category='overdue', rep='', company='', refresh=False, limit=50, offset=0, _=None, db=db)
    result = scope['list_followup_calls'](**kwargs)
    assert [row['lead_id'] for row in result['items']] == ['lead']
    assert result['items'][0]['smartmoving_id'] == 'sm-1'
    assert scope['list_followup_calls'](**{**kwargs, 'company': 'Other'})['items'] == []
    # Date filtering selects zero-priority leads without trimming their original schedule.
    from followup_tasks import lead_row
    tasks = db.query(Task).filter_by(lead_id=lead.id).all()
    day = tasks[0].due_date
    dated = scope['list_followup_calls'](**{**kwargs, 'category': 'all', 'priority': '0', 'date_from': day, 'date_to': day})
    assert len(dated['items']) == 1
    assert dated['items'][0]['timeline'] == lead_row(lead, tasks, datetime.now(timezone.utc))['timeline']
    # Nonzero priorities expose saved tasks without automatic-task generation.
    future = datetime.now(timezone.utc) + timedelta(days=30)
    manual = Task(lead_id=lead.id, title='Discuss estimate', task_type='other', status='open',
                  notes='Customer requested a call', due_date=future.date().isoformat(), due_at=future)
    db.add(manual)
    lead.priority = 2
    db.commit()
    for tab in ['2', 'all']:
        result = scope['list_followup_calls'](**{**kwargs, 'category': 'all', 'priority': tab,
            'date_from': future.date().isoformat(), 'date_to': future.date().isoformat()})
        assert [row['lead_id'] for row in result['items']] == ['lead']
        assert result['items'][0]['timeline'][0]['label'] == 'Discuss estimate'
    # The model requires a priority; filtering for unset priorities must not
    # require inserting invalid data or include a lead with a numeric priority.
    assert scope['list_followup_calls'](**{**kwargs, 'category': 'all', 'priority': 'none'})['items'] == []
    db.delete(manual)
    lead.priority = 0
    db.commit()

    task = db.query(Task).filter_by(task_type='call').first()
    task.due_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    result = scope['list_followup_calls'](**{**kwargs, 'category': 'due'})
    assert [row['lead_id'] for row in result['items']] == ['lead']
    assert result['counts'] == {'all': 1, 'overdue': 1, 'due': 1}
    message = db.query(Task).filter_by(task_type='text').first()
    message.due_at = datetime.now(timezone.utc) + timedelta(hours=1)
    task.status = 'done'
    db.commit()
    assert [row['lead_id'] for row in scope['list_followup_calls'](**{**kwargs, 'category': 'due'})['items']] == ['lead']
    message.status = 'done'
    task.status = 'open'
    task.scheduled_start = datetime.now(timezone.utc) + timedelta(minutes=30)
    db.commit()
    # Other overdue tasks still keep this lead in the inclusive Due view.
    result = scope['list_followup_calls'](**{**kwargs, 'category': 'due'})
    assert [row['lead_id'] for row in result['items']] == ['lead']
    assert result['counts']['due'] == 1
    lead.priority = 1
    db.commit()
    # Existing overdue tasks remain visible across priorities; the selected
    # priority tab determines whether this lead is included.
    for tab in ['all', '1']:
        result = scope['list_followup_calls'](**{**kwargs, 'priority': tab})
        assert [row['lead_id'] for row in result['items']] == ['lead']
    assert scope['list_followup_calls'](**{**kwargs, 'priority': '0'})['items'] == []
    for category in ['all', 'due', 'overdue']:
        result = scope['list_followup_calls'](**{**kwargs, 'category': category, 'priority': '1'})
        assert result['priority_counts'] == {'1': 1, 'all': 1}
    for saved_task in db.query(Task).filter_by(lead_id=lead.id).all():
        saved_task.status = 'done'
    db.commit()
    result = scope['list_followup_calls'](**kwargs)
    assert result['priority_counts'] == {'all': 0}
    assert result['counts'] == {'all': 0, 'due': 0, 'overdue': 0}
    replay.assert_not_called()


def test_contact_resolution_saves_triggering_evidence_without_overwriting_first():
    import json
    from sqlalchemy.dialects import postgresql
    from first_contact_state import contact_evidence, resolve
    db = Mock()
    db.get.return_value = object()
    db.query.return_value.filter_by.return_value.delete.return_value = 1
    evidence = contact_evidence('sms', {'message_id': 'sms-42', 'timestamp': 1792152000,
        'direction': 'sent', 'sales_name': 'Eli', 'phone_number': '2403703417',
        'company_number': '2029372625', 'body': 'Hello', 'secret': 'not stored'})
    occurred = datetime.fromisoformat(evidence['contacted_at'])
    assert resolve(db, 'lead-1', occurred, evidence, 'reload') == 1
    statement = db.execute.call_args_list[1].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    saved = json.loads(compiled.params['evidence'])
    assert saved['record_id'] == 'sms-42'
    assert saved['message'] == 'Hello'
    assert saved['was_pending'] is True
    assert saved['source'] == 'reload'
    assert 'secret' not in saved
    assert 'ON CONFLICT (lead_id) DO NOTHING' in str(compiled)


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
    import followup_tasks
    monkeypatch.setattr(followup_tasks, 'sync_saved_lead', Mock())
    db = Mock()
    db.__enter__ = Mock(return_value=db)
    db.__exit__ = Mock(return_value=False)
    lead = SimpleNamespace(id="saved", priority=0, status="new", company=None,
                           smartmoving_id=smartmoving_id, created_time="2026-10-01T12:00:00Z")
    db.query.return_value.options.return_value.filter_by.return_value.first.return_value = lead
    db.get.return_value = None
    monkeypatch.setitem(sys.modules, "database", SimpleNamespace(SessionLocal=lambda: db))
    history = Mock(side_effect=history_result) if isinstance(history_result, Exception) else Mock(return_value=history_result)
    if history_result is True:
        history.return_value = {'contacted_at': '2026-10-01T13:00:00+00:00', 'channel': 'sms', 'record_id': 'message-1'}
    resolve = Mock()
    monkeypatch.setattr(state, 'resolve', resolve)
    monkeypatch.setitem(sys.modules, "routes.unanswered_messages", SimpleNamespace(has_first_contact=history))
    state.add_created_lead("saved", created_in_smartmoving_here=created_here)
    assert history.call_count == int(should_check)
    if should_check:
        history.assert_called_once_with(lead, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), return_contact=True)
    assert resolve.call_count == int(history_result is True and should_check)
    assert db.commit.call_count == int(should_add or (history_result is True and should_check))
    assert db.execute.call_count == int(should_add)


def test_first_contact_page_reads_only_saved_pending_rows():
    source = Path(__file__).resolve().parents[2] / "backend/routes/unanswered_messages.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"list_first_contact_leads", "_queue_lead_options", "_with_smartmoving_links"}]
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
        db.add_all([Lead(id="pending", full_name="Pending", smartmoving_id="sm-pending", quote_number="27210", created_at=now-timedelta(hours=1)),
                    Lead(id="contacted", full_name="Contacted", created_at=now-timedelta(hours=1))])
        db.flush()
        waiting_since = now - timedelta(days=2)
        db.add(FirstContactState(lead_id="pending", waiting_since=waiting_since))
        db.commit()
        result = scope["list_first_contact_leads"](category="overdue", rep="", company="", refresh=False,
                                                    limit=50, offset=0, _=None, db=db)
        assert [row["lead_id"] for row in result["items"]] == ["pending"]
        assert result["items"][0]["smartmoving_id"] == "sm-pending"
        assert result["items"][0]["quote_number"] == "27210"
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
