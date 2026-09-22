"""Send portal codes with Cognito invitation email; CRM validates the code.

Dedicated pool without app clients: temporary passwords are delivery values,
not credentials accepted by any CRM/Cognito sign-in client.
"""
import hashlib
import os
import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException


def client():
    return boto3.client('cognito-idp', region_name=os.getenv('AWS_REGION', 'us-east-1'))


def send_email_code(email, code, access_id):
    pool = os.getenv('PUBLIC_MOVE_COGNITO_POOL_ID', '')
    if not pool:
        raise HTTPException(503, 'Email sending is not configured. Please use text message.')
    email = email.strip().lower()
    username = 'move-' + hashlib.sha256((access_id + ':' + email).encode()).hexdigest()
    args = dict(UserPoolId=pool, Username=username, TemporaryPassword=code,
        DesiredDeliveryMediums=['EMAIL'], UserAttributes=[{'Name': 'email', 'Value': email}])
    cognito = client()
    try:
        try:
            cognito.admin_create_user(**args)
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'UsernameExistsException': raise
            cognito.admin_create_user(**args, MessageAction='RESEND')
    except ClientError as exc:
        error = exc.response.get('Error', {}).get('Code', '')
        if error in ('TooManyRequestsException', 'LimitExceededException'):
            raise HTTPException(429, 'Email sending limit reached. Please try later or use text message.') from exc
        raise HTTPException(502, 'Could not send the email. Please try later or use text message.') from exc
