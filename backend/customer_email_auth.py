"""Cognito email OTP for the customer portal; Cognito tokens never reach clients."""
import base64
import hashlib
import hmac
import os
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException


def configuration():
    pool = os.getenv('PUBLIC_MOVE_COGNITO_POOL_ID', '')
    client_id = os.getenv('PUBLIC_MOVE_COGNITO_CLIENT_ID', '')
    if not pool or not client_id:
        raise HTTPException(503, 'Email verification is not configured. Please use text message or contact the moving team.')
    return pool, client_id


def client():
    return boto3.client('cognito-idp', region_name=os.getenv('AWS_REGION', 'us-east-1'))


@lru_cache(maxsize=4)
def client_secret(pool, client_id):
    return client().describe_user_pool_client(UserPoolId=pool, ClientId=client_id)['UserPoolClient']['ClientSecret']


def secret_hash(username, pool, client_id):
    return base64.b64encode(hmac.new(client_secret(pool, client_id).encode(),
        (username + client_id).encode(), hashlib.sha256).digest()).decode()


def provider_error(exc):
    code = exc.response.get('Error', {}).get('Code', '')
    if code in ('CodeMismatchException', 'NotAuthorizedException', 'ExpiredCodeException'):
        return HTTPException(400, 'Incorrect or expired code. Please request a new code and try again.')
    if code in ('TooManyRequestsException', 'LimitExceededException'):
        return HTTPException(429, 'Too many email verification requests. Please try later or use text message.')
    return HTTPException(502, 'Email verification is temporarily unavailable. Please use text message or try later.')


def send_email_code(email):
    pool, client_id = configuration()
    email = email.strip().lower()
    # Email changes produce a different immutable identity; never mark it verified here.
    username = 'customer-' + hashlib.sha256(email.encode()).hexdigest()
    cognito = client()
    try:
        try:
            cognito.admin_create_user(UserPoolId=pool, Username=username, MessageAction='SUPPRESS',
                UserAttributes=[{'Name': 'email', 'Value': email}])
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'UsernameExistsException': raise
        result = cognito.admin_initiate_auth(UserPoolId=pool, ClientId=client_id, AuthFlow='USER_AUTH',
            AuthParameters={'USERNAME': username, 'PREFERRED_CHALLENGE': 'EMAIL_OTP',
                'SECRET_HASH': secret_hash(username, pool, client_id)})
    except ClientError as exc:
        raise provider_error(exc) from exc
    if result.get('ChallengeName') != 'EMAIL_OTP' or not result.get('Session'):
        raise HTTPException(502, 'Email verification could not be started. Please use text message.')
    return {'username': username, 'session': result['Session']}


def verify_email_code(challenge, code):
    pool, client_id = configuration()
    username = challenge['username']
    try:
        result = client().admin_respond_to_auth_challenge(UserPoolId=pool, ClientId=client_id,
            ChallengeName='EMAIL_OTP', Session=challenge['session'], ChallengeResponses={
                'USERNAME': username, 'EMAIL_OTP_CODE': code,
                'SECRET_HASH': secret_hash(username, pool, client_id)})
    except ClientError as exc:
        raise provider_error(exc) from exc
    if not result.get('AuthenticationResult', {}).get('AccessToken'):
        raise HTTPException(400, 'Email verification was not completed. Request a new code.')
