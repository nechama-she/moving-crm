from unittest.mock import MagicMock
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
import customer_email_auth as auth


@pytest.fixture
def cognito(monkeypatch):
    monkeypatch.setenv('PUBLIC_MOVE_COGNITO_POOL_ID', 'pool')
    monkeypatch.setenv('PUBLIC_MOVE_COGNITO_CLIENT_ID', 'client')
    client = MagicMock()
    monkeypatch.setattr(auth, 'client', lambda: client)
    monkeypatch.setattr(auth, 'client_secret', lambda *args: 'secret')
    client.admin_initiate_auth.return_value = {'ChallengeName': 'EMAIL_OTP', 'Session': 'challenge'}
    return client


def test_email_start_does_not_preverify_or_send_invitation(cognito):
    challenge = auth.send_email_code('Jane@Example.com')
    args = cognito.admin_create_user.call_args.kwargs
    assert args['MessageAction'] == 'SUPPRESS'
    assert args['UserAttributes'] == [{'Name': 'email', 'Value': 'jane@example.com'}]
    assert 'TemporaryPassword' not in args
    assert challenge['session'] == 'challenge'
    assert cognito.admin_initiate_auth.call_args.kwargs['AuthParameters']['PREFERRED_CHALLENGE'] == 'EMAIL_OTP'


def test_existing_user_and_verification(cognito):
    cognito.admin_create_user.side_effect = ClientError({'Error': {'Code': 'UsernameExistsException'}}, 'AdminCreateUser')
    challenge = auth.send_email_code('jane@example.com')
    cognito.admin_respond_to_auth_challenge.return_value = {'AuthenticationResult': {'AccessToken': 'private-token'}}
    assert auth.verify_email_code(challenge, '123456') is None
    assert cognito.admin_respond_to_auth_challenge.call_args.kwargs['ChallengeResponses']['EMAIL_OTP_CODE'] == '123456'


def test_incomplete_auth_does_not_succeed(cognito):
    cognito.admin_respond_to_auth_challenge.return_value = {'ChallengeName': 'PASSWORD'}
    with pytest.raises(HTTPException): auth.verify_email_code({'username': 'customer', 'session': 'challenge'}, '123456')
