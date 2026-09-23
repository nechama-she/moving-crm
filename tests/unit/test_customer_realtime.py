import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import realtime_handler
import customer_report_updates as reports


@pytest.fixture
def sockets(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'testing-secret-at-least-thirty-two-characters')
    monkeypatch.setenv('REALTIME_CONNECTIONS_TABLE', 'connections')
    monkeypatch.setenv('REALTIME_MANAGEMENT_ENDPOINT', 'https://example.test/live')
    table, client = MagicMock(), MagicMock()
    monkeypatch.setattr(realtime_handler.boto3, 'resource', lambda *a: SimpleNamespace(Table=lambda *a: table))
    monkeypatch.setattr(realtime_handler.boto3, 'client', lambda *a, **kw: client)
    return table, client


def test_customer_socket_scoped_and_expiring(sockets):
    table, _ = sockets
    token = jwt.encode({'sub':'access-1', 'lead_id':'lead-1', 'purpose':'customer_updates',
        'role':'customer_updates', 'iss':'moving-crm', 'exp':int(time.time())+60},
        'testing-secret-at-least-thirty-two-characters', algorithm='HS256')
    event = {'requestContext':{'routeKey':'$connect','connectionId':'c'}, 'queryStringParameters':{'token':token}}
    assert realtime_handler.handler(event, None)['statusCode'] == 200
    row = table.put_item.call_args.kwargs['Item']
    assert row['customer_lead_id'] == 'lead-1'
    assert row['expires_at'] <= time.time()+60
    event['queryStringParameters']['token'] = 'bad'
    assert realtime_handler.handler(event, None)['statusCode'] == 401


@pytest.mark.parametrize('target,expected', [(None,['admin']), ('lead-1',['customer-1'])])
def test_broadcast_never_crosses_customer_or_staff_boundaries(sockets, target, expected):
    table, client = sockets
    expiry = int(time.time())+60
    table.scan.return_value = {'Items':[
        {'connection_id':'admin','expires_at':expiry},
        {'connection_id':'customer-1','customer_lead_id':'lead-1','expires_at':expiry},
        {'connection_id':'customer-2','customer_lead_id':'lead-2','expires_at':expiry},
        {'connection_id':'expired','customer_lead_id':'lead-1','expires_at':0},
    ]}
    payload = {'type':'customer_move_updated','customer_lead_id':target} if target else {'type':'staff_event'}
    realtime_handler.handler({'action':'broadcast','payload':payload}, None)
    assert [c.kwargs['ConnectionId'] for c in client.post_to_connection.call_args_list] == expected


@pytest.fixture
def monitor(monkeypatch):
    state = {'last_spark_id':'report-1','last_spark_status':'queued'}
    saved = SimpleNamespace(details=json.dumps(state))
    db = MagicMock()
    db.get.return_value = saved
    db.query.return_value.filter_by.return_value.populate_existing.return_value.with_for_update.return_value.first.return_value = saved
    api = MagicMock(return_value={'status':'completed','shareUrl':'https://example.test/report'})
    apply = MagicMock(return_value={'ok':True})
    monkeypatch.setitem(sys.modules,'routes.liveswitch',SimpleNamespace(_api_get=api,apply_spark_results_to_lead=apply))
    publish, sqs = MagicMock(), MagicMock()
    monkeypatch.setattr(reports,'publish_customer_update',publish)
    monkeypatch.setattr(reports.boto3,'client',lambda *a,**kw:sqs)
    monkeypatch.setenv('PUBLIC_MOVE_SYNC_QUEUE_URL','queue')
    return saved, db, api, apply, publish, sqs


def test_completed_report_is_processed_without_browser_request(monitor):
    saved, db, api, apply, publish, sqs = monitor
    reports.check_report({'lead_id':'lead','check_report':'report-1'},db)
    apply.assert_called_once_with('lead','https://example.test/report',db,expected_report_id='report-1')
    sqs.send_message.assert_not_called()


def test_stale_report_cannot_replace_new_report(monitor):
    saved, db, api, apply, publish, sqs = monitor
    reports.check_report({'lead_id':'lead','check_report':'old-report'},db)
    api.assert_not_called()
    apply.assert_not_called()
    sqs.send_message.assert_not_called()


def test_monitor_is_bounded_and_exposes_failure(monitor):
    saved, db, api, apply, publish, sqs = monitor
    api.return_value = {'status':'running'}
    reports.check_report({'lead_id':'lead','check_report':'report-1','attempt':119},db)
    sqs.send_message.assert_not_called()
    assert 'notification_error' in json.loads(saved.details)
    publish.assert_called_with('lead')


def test_reconnect_does_not_duplicate_report_monitor(monitor):
    saved, db, api, apply, publish, sqs = monitor
    reports.queue_report_check('lead',db)
    reports.queue_report_check('lead',db)
    sqs.send_message.assert_called_once()


def test_running_report_requeues_on_server_only(monitor):
    saved, db, api, apply, publish, sqs = monitor
    api.return_value = {'status':'running'}
    reports.check_report({'lead_id':'lead','check_report':'report-1'},db)
    assert sqs.send_message.call_args.kwargs['DelaySeconds'] == 60
    assert json.loads(sqs.send_message.call_args.kwargs['MessageBody'])['attempt'] == 1
    apply.assert_not_called()


def test_report_socket_is_scoped_to_authorized_lead(sockets):
    table, _ = sockets
    claims = {'sub': 'report-updates:staff', 'role': 'report_updates', 'purpose': 'report_updates',
              'lead_id': 'lead-1', 'iss': 'moving-crm', 'exp': int(time.time()) + 60}
    token = jwt.encode(claims, 'testing-secret-at-least-thirty-two-characters', algorithm='HS256')
    event = {'requestContext': {'routeKey': '$connect', 'connectionId': 'report'}, 'queryStringParameters': {'token': token}}
    assert realtime_handler.handler(event, None)['statusCode'] == 200
    assert table.put_item.call_args.kwargs['Item']['report_lead_id'] == 'lead-1'
    del claims['purpose']
    event['queryStringParameters']['token'] = jwt.encode(claims, 'testing-secret-at-least-thirty-two-characters', algorithm='HS256')
    assert realtime_handler.handler(event, None)['statusCode'] == 403


@pytest.mark.parametrize('payload,expected', [
    ({'type':'report_updated','report_lead_id':'lead-1'}, ['report-1']),
    ({'type':'customer_move_updated','customer_lead_id':'lead-1'}, ['customer']),
    ({'type':'staff_event'}, ['admin'])])
def test_report_events_do_not_cross_subscriptions(sockets, payload, expected):
    table, client = sockets
    expiry = int(time.time()) + 60
    table.scan.return_value = {'Items': [
        {'connection_id':'report-1', 'report_lead_id':'lead-1', 'expires_at':expiry},
        {'connection_id':'report-2', 'report_lead_id':'lead-2', 'expires_at':expiry},
        {'connection_id':'expired', 'report_lead_id':'lead-1', 'expires_at':0},
        {'connection_id':'customer', 'customer_lead_id':'lead-1', 'expires_at':expiry},
        {'connection_id':'admin', 'expires_at':expiry}]}
    realtime_handler.handler({'action':'broadcast','payload':payload}, None)
    assert [call.kwargs['ConnectionId'] for call in client.post_to_connection.call_args_list] == expected


def test_processing_notification_follows_commit(monkeypatch):
    import realtime
    from spark_processing import SparkProcessingLog
    saved = SimpleNamespace(details=json.dumps({'last_spark_id':'report'}))
    db = MagicMock()
    db.get.return_value = saved
    def notified(lead):
        db.commit.assert_called_once()
        assert json.loads(saved.details)['spark_processing']['status'] == 'running'
        assert lead == 'lead'
    publish = MagicMock(side_effect=notified)
    monkeypatch.setattr(realtime, 'publish_report_update', publish)
    SparkProcessingLog('report').persist(db, 'lead')
    publish.assert_called_once()
