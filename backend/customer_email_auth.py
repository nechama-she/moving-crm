"""Send portal codes with Cognito invitation email; CRM validates the code.

Dedicated pool without app clients: temporary passwords are delivery values,
not credentials accepted by any CRM/Cognito sign-in client.
"""
import hashlib
import json
import logging
import os
import re
from uuid import uuid4
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

logger = logging.getLogger('moving-crm.customer-email')
logger.setLevel(logging.INFO)


def client():
    return boto3.client('cognito-idp', region_name=os.getenv('AWS_REGION', 'us-east-1'))


def send_email_code(email, code, access_id):
    pool = os.getenv('PUBLIC_MOVE_COGNITO_POOL_ID', '')
    email = email.strip().lower()
    username = 'move-' + hashlib.sha256((access_id + ':' + email).encode()).hexdigest()
    attempt_id = str(uuid4())

    def record(status, action='CREATE', response=None, error_code=None, error_message=None):
        metadata = (response or {}).get('ResponseMetadata', {})
        # Never log the invitation payload, temporary password, or complete recipient.
        event = {'event': 'customer_email_send', 'attempt_id': attempt_id,
                 'access_id': access_id, 'user_pool_id': pool, 'cognito_username': username,
                 'recipient_masked': email[:1] + '***@' + email.partition('@')[2],
                 'status': status, 'action': action,
                 'aws_request_id': metadata.get('RequestId'), 'http_status': metadata.get('HTTPStatusCode')}
        if error_code:
            event['error_code'] = error_code
        if error_message:
            message = re.sub(re.escape(email), '[recipient]', str(error_message), flags=re.IGNORECASE)
            event['error_message'] = message.replace(code, '[redacted]')[:1000]
        logger.log(logging.ERROR if status in ('failed', 'unknown') else logging.INFO, json.dumps(event, default=str))

    if not pool:
        record('failed', error_code='EmailPoolNotConfigured', error_message='Customer email pool is not configured')
        raise HTTPException(503, 'Email sending is not configured. Please use text message.')
    args = dict(UserPoolId=pool, Username=username, TemporaryPassword=code,
        DesiredDeliveryMediums=['EMAIL'], UserAttributes=[{'Name': 'email', 'Value': email}])
    action = 'CREATE'
    record('attempting', action)
    try:
        cognito = client()
        try:
            response = cognito.admin_create_user(**args)
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'UsernameExistsException': raise
            action = 'RESEND'
            record('attempting', action, exc.response)
            response = cognito.admin_create_user(**args, MessageAction='RESEND')
        # API acceptance is not a recipient delivery receipt.
        record('accepted', action, response)
    except ClientError as exc:
        error = exc.response.get('Error', {}).get('Code', '')
        record('failed', action, exc.response, error, exc.response.get('Error', {}).get('Message', ''))
        if error in ('TooManyRequestsException', 'LimitExceededException'):
            raise HTTPException(429, 'Email sending limit reached. Please try later or use text message.') from exc
        raise HTTPException(502, 'Could not send the email. Please try later or use text message.') from exc
    except BotoCoreError as exc:
        # A transport failure can happen after AWS accepted a request.
        record('unknown', action, error_code=type(exc).__name__, error_message='AWS SDK or transport failure; acceptance could not be confirmed')
        raise HTTPException(502, 'Could not confirm the email was sent. Please try later or use text message.') from exc
