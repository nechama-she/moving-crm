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


@pytest.fixture
def ses(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(auth, 'ses_client', lambda: client)
    return client


def company(sender='sales@gorillahaulers.com', name='Gorilla Haulers'):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, sender_email=sender)


def test_company_sender_sends_via_ses_not_cognito(cognito, ses):
    auth.send_email_code('Jane@Example.com', '123456', 'access', company())
    args = ses.send_email.call_args.kwargs
    assert args['FromEmailAddress'] == 'Gorilla Haulers <sales@gorillahaulers.com>'
    assert args['ReplyToAddresses'] == ['sales@gorillahaulers.com']
    assert args['Destination'] == {'ToAddresses': ['jane@example.com']}
    content = args['Content']['Simple']
    assert '123456' in content['Body']['Text']['Data'] and '123456' in content['Body']['Html']['Data']
    assert 'Gorilla Haulers' in content['Subject']['Data']
    cognito.admin_create_user.assert_not_called()


def test_company_without_sender_falls_back_to_cognito(cognito, ses):
    auth.send_email_code('jane@example.com', '123456', 'access', company(sender=''))
    ses.send_email.assert_not_called()
    cognito.admin_create_user.assert_called_once()


def test_company_name_is_html_escaped(cognito, ses):
    auth.send_email_code('jane@example.com', '123456', 'access', company(name='A&B <Movers>'))
    html_body = ses.send_email.call_args.kwargs['Content']['Simple']['Body']['Html']['Data']
    assert 'A&amp;B &lt;Movers&gt;' in html_body and '<Movers>' not in html_body


def test_ses_rejection_is_502_and_logged_without_code(cognito, ses, caplog):
    ses.send_email.side_effect = ClientError({'Error': {'Code': 'MessageRejected', 'Message': 'Email address is not verified: 913725'},
                                              'ResponseMetadata': {'RequestId': 'ses-req'}}, 'SendEmail')
    with pytest.raises(HTTPException) as error: auth.send_email_code('jane@example.com', '913725', 'access-1', company())
    assert error.value.status_code == 502
    event = email_events(caplog)[-1]
    assert (event['status'], event['action'], event['error_code']) == ('failed', 'SES', 'MessageRejected')
    assert event['sender'] == 'sales@gorillahaulers.com'
    assert '913725' not in caplog.text and 'jane@example.com' not in caplog.text


def test_ses_throttling_is_429(cognito, ses):
    ses.send_email.side_effect = ClientError({'Error': {'Code': 'TooManyRequestsException'}}, 'SendEmail')
    with pytest.raises(HTTPException) as error: auth.send_email_code('jane@example.com', '123456', 'access', company())
    assert error.value.status_code == 429


def test_missing_pool_is_logged(cognito, caplog, monkeypatch):
    monkeypatch.delenv('PUBLIC_MOVE_COGNITO_POOL_ID')
    with pytest.raises(HTTPException): auth.send_email_code('jane@example.com','913725','access-1')
    assert email_events(caplog)[-1]['error_code']=='EmailPoolNotConfigured'
    cognito.admin_create_user.assert_not_called()
