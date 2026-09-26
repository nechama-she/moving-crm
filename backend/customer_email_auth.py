"""Send customer portal codes by email; CRM validates the code.

Preferred path: SES, sent from the lead's company address (``Company.sender_email``,
whose domain must be verified in SES with DKIM) so the mail is legitimately from
that provider and lands in the inbox.

Fallback (company has no sender configured): Cognito invitation email from the
shared ``no-reply@verificationemail.com`` address. Dedicated pool without app
clients: temporary passwords are delivery values, not credentials accepted by
any CRM/Cognito sign-in client.
"""
import hashlib
import html
import json
import logging
import os
import re
from email.utils import formataddr
from uuid import uuid4
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

logger = logging.getLogger('moving-crm.customer-email')
logger.setLevel(logging.INFO)


def client():
    return boto3.client('cognito-idp', region_name=os.getenv('AWS_REGION', 'us-east-1'))


def ses_client():
    return boto3.client('sesv2', region_name=os.getenv('AWS_REGION', 'us-east-1'))


def _code_email(code, company_name):
    subject = f'Your {company_name} verification code'
    text = (f'Your {company_name} verification code is {code}.\n\n'
            'Enter it on your moving page. This code expires in 10 minutes. '
            'Do not share it with anyone.\n\n'
            f'If you did not request this code, you can ignore this email.\n\n{company_name}')
    name = html.escape(company_name)
    body = (f'<p>Your {name} verification code is:</p>'
            f'<p style="font-size:24px;font-weight:bold;letter-spacing:4px">{code}</p>'
            '<p>Enter it on your moving page. This code expires in 10 minutes. Do not share it with anyone.</p>'
            '<p>If you did not request this code, you can ignore this email.</p>'
            f'<p>{name}</p>')
    return subject, text, body


def send_email_code(email, code, access_id, company=None):
    pool = os.getenv('PUBLIC_MOVE_COGNITO_POOL_ID', '')
    email = email.strip().lower()
    username = 'move-' + hashlib.sha256((access_id + ':' + email).encode()).hexdigest()
    attempt_id = str(uuid4())
    sender = ((getattr(company, 'sender_email', None) or '') if company else '').strip()

    def record(status, action='CREATE', response=None, error_code=None, error_message=None):
        metadata = (response or {}).get('ResponseMetadata', {})
        # Never log the invitation payload, temporary password, or complete recipient.
        event = {'event': 'customer_email_send', 'attempt_id': attempt_id,
                 'access_id': access_id, 'user_pool_id': pool, 'cognito_username': username,
                 'recipient_masked': email[:1] + '***@' + email.partition('@')[2],
                 'status': status, 'action': action,
                 'aws_request_id': metadata.get('RequestId'), 'http_status': metadata.get('HTTPStatusCode')}
        if sender:
            event['sender'] = sender
        if error_code:
            event['error_code'] = error_code
        if error_message:
            message = re.sub(re.escape(email), '[recipient]', str(error_message), flags=re.IGNORECASE)
            event['error_message'] = message.replace(code, '[redacted]')[:1000]
        logger.log(logging.ERROR if status in ('failed', 'unknown') else logging.INFO, json.dumps(event, default=str))

    if sender:
        company_name = (getattr(company, 'name', None) or '').strip() or 'Your moving team'
        subject, text, body = _code_email(code, company_name)
        record('attempting', 'SES')
        try:
            response = ses_client().send_email(
                FromEmailAddress=formataddr((company_name, sender)),
                ReplyToAddresses=[sender],
                Destination={'ToAddresses': [email]},
                Content={'Simple': {
                    'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                    'Body': {'Text': {'Data': text, 'Charset': 'UTF-8'},
                             'Html': {'Data': body, 'Charset': 'UTF-8'}},
                }})
            # API acceptance is not a recipient delivery receipt.
            record('accepted', 'SES', response)
        except ClientError as exc:
            error = exc.response.get('Error', {}).get('Code', '')
            record('failed', 'SES', exc.response, error, exc.response.get('Error', {}).get('Message', ''))
            if error in ('TooManyRequestsException', 'LimitExceededException', 'SendingPausedException'):
                raise HTTPException(429, 'Email sending limit reached. Please try later or use text message.') from exc
            raise HTTPException(502, 'Could not send the email. Please try later or use text message.') from exc
        except BotoCoreError as exc:
            record('unknown', 'SES', error_code=type(exc).__name__, error_message='AWS SDK or transport failure; acceptance could not be confirmed')
            raise HTTPException(502, 'Could not confirm the email was sent. Please try later or use text message.') from exc
        return

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
