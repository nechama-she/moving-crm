from unittest.mock import MagicMock
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
import customer_email_auth as auth

@pytest.fixture
def cognito(monkeypatch):
    monkeypatch.setenv('PUBLIC_MOVE_COGNITO_POOL_ID', 'pool')
    client = MagicMock()
    monkeypatch.setattr(auth, 'client', lambda: client)
    return client

def test_first_email_uses_default_invitation(cognito):
    auth.send_email_code('Jane@Example.com', '123456', 'access')
    args = cognito.admin_create_user.call_args.kwargs
    assert 'MessageAction' not in args
    assert args['TemporaryPassword'] == '123456'
    assert args['DesiredDeliveryMediums'] == ['EMAIL']
    assert args['UserAttributes'] == [{'Name': 'email', 'Value': 'jane@example.com'}]

def test_existing_user_resends_new_code(cognito):
    cognito.admin_create_user.side_effect = [ClientError({'Error': {'Code': 'UsernameExistsException'}}, 'AdminCreateUser'), {}]
    auth.send_email_code('jane@example.com', '654321', 'access')
    assert cognito.admin_create_user.call_args.kwargs['MessageAction'] == 'RESEND'
    assert cognito.admin_create_user.call_args.kwargs['TemporaryPassword'] == '654321'

def test_send_failure_is_not_success(cognito):
    cognito.admin_create_user.side_effect = ClientError({'Error': {'Code': 'CodeDeliveryFailureException'}}, 'AdminCreateUser')
    with pytest.raises(HTTPException) as error: auth.send_email_code('jane@example.com', '123456', 'access')
    assert error.value.status_code == 502

def test_each_move_and_email_have_distinct_identity(cognito):
    for access, email in [('a', 'jane@example.com'), ('b', 'jane@example.com'), ('a', 'other@example.com')]:
        auth.send_email_code(email, '123456', access)
    assert len({call.kwargs['Username'] for call in cognito.admin_create_user.call_args_list}) == 3

def email_events(caplog):
    import json
    return [json.loads(record.message) for record in caplog.records if record.name == 'moving-crm.customer-email']


def test_email_acceptance_is_traceable_without_logging_code(cognito, caplog):
    cognito.admin_create_user.return_value={'ResponseMetadata':{'RequestId':'aws-request-1','HTTPStatusCode':200}}
    auth.send_email_code('jane@example.com','913725','access-1')
    events=email_events(caplog)
    assert [e['status'] for e in events]==['attempting','accepted']
    assert events[-1]['aws_request_id']=='aws-request-1'
    assert events[-1]['access_id']=='access-1'
    assert events[-1]['attempt_id']==events[0]['attempt_id']
    assert '913725' not in caplog.text and 'jane@example.com' not in caplog.text
    assert not any(e['status']=='delivered' for e in events)


def test_resend_events_share_attempt_id(cognito, caplog):
    cognito.admin_create_user.side_effect=[ClientError({'Error':{'Code':'UsernameExistsException'}},'AdminCreateUser'), {'ResponseMetadata':{'RequestId':'resend-request'}}]
    auth.send_email_code('jane@example.com','913725','access-1')
    events=email_events(caplog)
    assert [(e['status'],e['action']) for e in events]==[('attempting','CREATE'),('attempting','RESEND'),('accepted','RESEND')]
    assert len({e['attempt_id'] for e in events})==1


def test_aws_email_error_logs_redacted_message(cognito, caplog):
    cognito.admin_create_user.side_effect=ClientError({'Error':{'Code':'CodeDeliveryFailureException','Message':'Could not deliver to Jane@Example.com with 913725'},'ResponseMetadata':{'RequestId':'failed-request','HTTPStatusCode':400}},'AdminCreateUser')
    with pytest.raises(HTTPException): auth.send_email_code('jane@example.com','913725','access-1')
    event=email_events(caplog)[-1]
    assert event['status']=='failed'
    assert event['error_code']=='CodeDeliveryFailureException'
    assert event['aws_request_id']=='failed-request'
    assert '913725' not in caplog.text and 'Jane@Example.com' not in caplog.text
    assert '[redacted]' in event['error_message']


def test_transport_error_is_unknown_not_delivery_failure(cognito, caplog):
    from botocore.exceptions import EndpointConnectionError
    cognito.admin_create_user.side_effect=EndpointConnectionError(endpoint_url='https://cognito-idp.us-east-1.amazonaws.com')
    with pytest.raises(HTTPException) as exc: auth.send_email_code('jane@example.com','913725','access-1')
    assert exc.value.status_code==502
    assert email_events(caplog)[-1]['status']=='unknown'


def test_missing_pool_is_logged(cognito, caplog, monkeypatch):
    monkeypatch.delenv('PUBLIC_MOVE_COGNITO_POOL_ID')
    with pytest.raises(HTTPException): auth.send_email_code('jane@example.com','913725','access-1')
    assert email_events(caplog)[-1]['error_code']=='EmailPoolNotConfigured'
    cognito.admin_create_user.assert_not_called()
