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
