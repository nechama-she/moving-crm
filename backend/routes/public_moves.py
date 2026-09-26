"""Verified, job-scoped public access. Staff credentials never enter the public page."""
from manual_inventory import ManualInventoryInput, catalog, submit_inventory, save_inventory_draft
from spark_history import report_history
from pricing_addresses import with_job_locations
from report_files import move_files, file_list, remove_report_file, preview_report_file
import hmac
import json
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import case, func, or_, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from config import get_config
from company_colors import resolve_company_color
from database import get_db
from libs.aircall.client import find_number_id, send_sms
from models import Lead, LeadJob, Company, User, LeadAttachment, LeadLiveSwitch, PublicMoveAccess, PublicMoveSession, PublicMoveRepVerification, PublicMoveUpload, PublicMoveRate, PublicMovePendingUpload, WalkthroughRequest
from public_move_security import digest, secret_digest, link_token, contact_fingerprint, normalize_phone, file_type
from public_move_sync import queue_files, sync_status
from routes.leads import _get_visible_lead_or_404, _get_user_company_ids, _persist_job_route, _read_job_route, _upload_attachment_bytes_to_s3, _delete_s3_url, _safe_attachment_name

router = APIRouter(tags=['Customer move portal'])
NOW = datetime.utcnow


def setting(name):
    return str(get_config().get(name) or os.getenv(name, '')).strip()


def rate(db, key, limit=90, seconds=60):
    window = int(time.time()) // seconds
    hashed = digest(key)
    stmt = insert(PublicMoveRate).values(key=hashed, window=window, count=1)
    stmt = stmt.on_conflict_do_update(index_elements=['key'], set_={
        'window': window,
        'count': case((PublicMoveRate.window == window, PublicMoveRate.count + 1), else_=1),
    }).returning(PublicMoveRate.count)
    count = db.execute(stmt).scalar_one()
    db.commit()
    if count > limit:
        raise HTTPException(429, 'Too many requests. Please try again later.', headers={'Retry-After': str(seconds)})


def public_access(access_id: str, request: Request, db: Session = Depends(get_db)):
    rate(db, 'ip:' + (request.client.host if request.client else 'unknown'), 120)
    row = db.get(PublicMoveAccess, access_id)
    supplied = request.headers.get('x-public-link', '')
    if not row or row.revoked or row.expires_at < NOW() or not (hmac.compare_digest(row.token_hash, digest(supplied)) or is_rep_request(row, request)):
        raise HTTPException(404, 'This link is unavailable or expired. Please contact your moving team.')
    return row


def rep_link_token(access):
    return secret_digest('rep-move-link:' + access.id + ':' + access.token_hash)


def is_rep_request(access, request):
    return bool(request and hmac.compare_digest(request.headers.get('x-public-link', ''), rep_link_token(access)))


def rep_contacts(access, db):
    lead = db.get(Lead, access.lead_id)
    job = db.get(LeadJob, access.job_id)
    company_id = (job.company_id if job else None) or lead.company_id
    company = db.get(Company, company_id) if company_id else db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    rep = db.get(User, lead.assigned_to) if lead.assigned_to else None
    contacts = {}
    for channel, label, phone in [('rep_sms', 'Assigned rep', rep.phone if rep else None),
                                  ('company_sms', 'Company phone', company.phone if company else None)]:
        try:
            normalized = normalize_phone(phone)
        except ValueError:
            continue
        contacts[channel] = {'label': label, 'phone': normalized}
    fingerprint = secret_digest('rep-contact:' + json.dumps([lead.assigned_to, company.id if company else None, contacts], sort_keys=True))
    return contacts, fingerprint, company


def verification_fingerprint(access, db, request):
    if is_rep_request(access, request):
        return rep_contacts(access, db)[1]
    return contact_fingerprint(db.get(Lead, access.lead_id))


def verification_state(access, db, request):
    if not is_rep_request(access, request):
        return access
    # The caller holds the access-row lock, which serializes first creation too.
    state = db.get(PublicMoveRepVerification, access.id)
    if state is None:
        state = PublicMoveRepVerification(id=access.id)
        db.add(state)
        db.flush()
    return state


def verified(access: PublicMoveAccess = Depends(public_access), request: Request = None, db: Session = Depends(get_db)):
    session = db.get(PublicMoveSession, digest(request.headers.get('x-public-session', '')))
    lead = db.get(Lead, access.lead_id)
    if not session or session.access_id != access.id or session.expires_at < NOW() or session.contact_hash != verification_fingerprint(access, db, request):
        raise HTTPException(401, 'Please verify your phone or email to continue.')
    return access


@router.post('/api/public-moves/{access_id}/realtime-token')
def customer_realtime_token(access: PublicMoveAccess = Depends(verified), request: Request = None, db: Session = Depends(get_db)):
    import jwt
    session = db.get(PublicMoveSession, digest(request.headers.get('x-public-session', '')))
    expires = min(access.expires_at, session.expires_at, NOW() + timedelta(hours=2))
    token = jwt.encode({'sub': access.id, 'role': 'customer_updates', 'purpose': 'customer_updates',
                        'lead_id': access.lead_id, 'iss': os.getenv('JWT_ISSUER', 'moving-crm'),
                        'exp': int(expires.replace(tzinfo=timezone.utc).timestamp())},
                       os.environ['JWT_SECRET'], algorithm='HS256')
    from customer_report_updates import queue_report_check
    queue_report_check(access.lead_id, db)
    return {'token': token}


class Stop(BaseModel):
    address: str = Field(min_length=1, max_length=1000)
    type: Literal['pickup', 'delivery'] | None = None

    @field_validator('address')
    @classmethod
    def address_required(cls, value):
        if not value.strip(): raise ValueError('Stop address is required')
        return value.strip()


class Intake(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=50)
    company_id: str | None = None
    move_date: date
    pickup: str = Field(min_length=1, max_length=1000)
    delivery: str = Field(min_length=1, max_length=1000)
    stops: list[Stop] = Field(default_factory=list, max_length=20)
    phone: str = Field(min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=254)

    @field_validator('first_name', 'last_name', 'source', 'pickup', 'delivery')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('This field is required')
        return value.strip()

    @field_validator('phone')
    @classmethod
    def phone_number(cls, value):
        return normalize_phone(value)

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        if not value or not value.strip(): return None
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value): raise ValueError('Provide a valid email address')
        return value


def public_url(row, rep=False):
    origin = setting('PUBLIC_MOVE_ORIGIN').rstrip('/')
    if not origin.startswith('https://'):
        raise HTTPException(503, 'The customer website origin is not configured')
    return f'{origin}/move/{row.id}#key={rep_link_token(row) if rep else link_token(row.id)}' + ('&audience=rep' if rep else '')


def create_customer_page_access(db, lead, job, key_hash, request_hash):
    access_id = str(uuid4())
    access = PublicMoveAccess(id=access_id, lead_id=lead.id, job_id=job.id, key_hash=key_hash,
                              request_hash=request_hash, token_hash=digest(link_token(access_id)),
                              expires_at=NOW()+timedelta(days=90))
    db.add(access)
    return access


@router.post('/api/inventory')
def intake(body: Intake, request: Request, x_api_secret: str = Header(default=''), idempotency_key: str = Header(min_length=8, max_length=128), db: Session = Depends(get_db)):
    # Trace only this endpoint's operations; keep credentials and SQL parameters out.
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder
    from sqlalchemy.exc import SQLAlchemyError

    definitions = [
        ('authenticate', 'endpoint'), ('rate_limit', 'db'),
        ('idempotency_lock', 'db'), ('find_existing_request', 'db'),
        ('validate_existing_request', 'endpoint'), ('validate_company', 'db'),
        ('create_lead', 'db'), ('create_job', 'db'), ('save_job_route', 'db'),
        ('create_customer_access', 'db'), ('commit', 'db'),
        ('build_customer_url', 'endpoint'), ('send_customer_sms', 'aircall'), ('send_customer_email', 'ses'), ('rollback', 'db'),
    ]
    actions = [dict(action=name, target=target, status='not_attempted', response=None, error=None)
               for name, target in definitions]
    by_name = {row['action']: row for row in actions}
    current = None
    committed = False
    result = {}

    def run(name, operation, response=lambda value: value):
        nonlocal current
        current = by_name[name]
        current['status'] = 'in_progress'
        value = operation()
        current.update(status='succeeded', response=response(value))
        return value

    def authenticate():
        expected = setting('PUBLIC_MOVE_API_KEY')
        if not expected or not hmac.compare_digest(expected, x_api_secret):
            raise HTTPException(401, 'Not authorized')
        return expected

    try:
        expected = run('authenticate', authenticate, lambda _: {'authorized': True})
        run('rate_limit', lambda: rate(db, 'intake:' + digest(expected), 60), lambda _: {'allowed': True})
        key = secret_digest('intake:' + idempotency_key)
        run('idempotency_lock', lambda: db.execute(text('SELECT pg_advisory_xact_lock(:key)'),
            {'key': int(key[:15], 16)}), lambda _: {'acquired': True})
        payload_hash = digest(json.dumps(body.model_dump(mode='json'), sort_keys=True))
        existing = run('find_existing_request', lambda: db.query(PublicMoveAccess).filter(
            PublicMoveAccess.key_hash == key).first(), lambda row: {'found': row is not None})
        if existing:
            def validate_existing():
                if existing.request_hash != payload_hash:
                    raise HTTPException(409, 'Idempotency key was already used for different details')
                if existing.revoked or existing.expires_at < NOW():
                    raise HTTPException(409, 'This request exists but its link has expired or was revoked')
                return {'reused': True}
            run('validate_existing_request', validate_existing)
            result = {'lead_id': existing.lead_id, 'job_id': existing.job_id}
            access = existing
        else:
            def validate_company():
                if body.company_id and not db.get(Company, body.company_id):
                    raise HTTPException(400, 'Unknown company')
                return {'company_id': body.company_id, 'valid': True}
            run('validate_company', validate_company)
            def create_lead():
                row = Lead(full_name=f'{body.first_name} {body.last_name}', company_id=body.company_id, source=body.source,
                    phone=body.phone, email=body.email, move_date=body.move_date.isoformat(), pickup_zip=body.pickup,
                    delivery_zip=body.delivery, status='new')
                db.add(row)
                db.flush()
                return row
            lead = run('create_lead', create_lead, lambda row: {'lead_id': row.id})
            def create_job():
                row = LeadJob(lead_id=lead.id, company_id=body.company_id, job_order=1,
                    move_date=body.move_date.isoformat(), pickup_zip=body.pickup, delivery_zip=body.delivery,
                    stop_types=json.dumps([stop.model_dump() for stop in body.stops]))
                db.add(row)
                db.flush()
                return row
            job = run('create_job', create_job, lambda row: {'job_id': row.id})
            run('save_job_route', lambda: _persist_job_route(db, job.id, body.pickup,
                [stop.address for stop in body.stops], body.delivery),
                lambda _: {'job_id': job.id, 'pickup_count': 1, 'stop_count': len(body.stops), 'delivery_count': 1})
            access = run('create_customer_access', lambda: create_customer_page_access(db, lead, job, key, payload_hash),
                lambda row: {'access_id': row.id, 'expires_at': row.expires_at})
            # Capture IDs before commit expires ORM attributes.
            result = {'lead_id': lead.id, 'job_id': job.id}
            run('commit', db.commit, lambda _: {'committed': True})
            committed = True
        url = run('build_customer_url', lambda: public_url(access), lambda value: {'url': value})
        result['url'] = url
        failures = []
        dry_run = (setting('PUBLIC_MOVE_LINK_DRY_RUN') or 'true').strip().lower() != 'false'
        for name, recipient, deliver in [
            ('send_customer_sms', lead.phone if existing is None else None, deliver_customer_link_sms),
            ('send_customer_email', lead.email if existing is None else None, deliver_customer_link_email),
        ]:
            if existing is not None:
                by_name[name]['response'] = {'message': 'Existing submission; customer link is not resent.'}
            elif not recipient or not recipient.strip():
                by_name[name]['response'] = {'message': 'No recipient provided.'}
            elif dry_run:
                by_name[name]['response'] = {'dry_run': True, 'message': 'Customer-link delivery is disabled by PUBLIC_MOVE_LINK_DRY_RUN.'}
            else:
                try:
                    run(name, lambda: deliver(lead, access, db))
                except Exception as delivery_error:
                    by_name[name].update(status='failed', error={
                        'type': type(delivery_error).__name__,
                        'message': delivery_error.detail if isinstance(delivery_error, HTTPException) else 'The message provider could not send this message.',
                        'http_status': delivery_error.status_code if isinstance(delivery_error, HTTPException) else 502})
                    failures.append((name, delivery_error))
        if failures:
            name, delivery_error = failures[0]
            current = by_name[name]
            if isinstance(delivery_error, HTTPException): raise delivery_error
            raise HTTPException(502, 'The message provider could not send this message.')
        return {**result, 'status': 'succeeded', 'reused': existing is not None, 'actions': actions}
    except Exception as exc:
        code = exc.status_code if isinstance(exc, HTTPException) else 500
        # SQLAlchemy exception strings include SQL and bound customer data.
        if isinstance(exc, HTTPException):
            message = exc.detail
        elif isinstance(exc, SQLAlchemyError):
            message = 'Database operation failed.'
        else:
            message = 'The operation failed unexpectedly.'
        error = {'type': type(exc).__name__, 'message': message, 'http_status': code}
        if isinstance(exc, SQLAlchemyError):
            sqlstate = getattr(getattr(exc, 'orig', None), 'sqlstate', None) or getattr(getattr(exc, 'orig', None), 'pgcode', None)
            if sqlstate: error['database_code'] = sqlstate
        if current is not None:
            current.update(status='failed', error=error)
        try:
            db.rollback()
            by_name['rollback'].update(status='succeeded', response={'rolled_back': True})
            if not committed:
                for name in ('create_lead', 'create_job', 'save_job_route', 'create_customer_access'):
                    if by_name[name]['status'] == 'succeeded': by_name[name]['status'] = 'rolled_back'
        except Exception as rollback_error:
            by_name['rollback'].update(status='failed', error={'type': type(rollback_error).__name__,
                'message': 'Database rollback failed.'})
        return JSONResponse(status_code=code, headers=exc.headers if isinstance(exc, HTTPException) else None,
            content=jsonable_encoder({**(result if committed else {}), 'status': 'partial' if committed else 'failed',
                'detail': message, 'error': error, 'actions': actions}))


@router.get('/api/public-moves/{access_id}/verify-options')
def verify_options(access: PublicMoveAccess = Depends(public_access), db: Session = Depends(get_db), request: Request = None):
    lead = db.get(Lead, access.lead_id)
    active_company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    company_color = active_company.color if active_company and active_company.color else resolve_company_color(active_company.name if active_company else None, None)
    if is_rep_request(access, request):
        contacts, _, company = rep_contacts(access, db)
        return {'audience': 'rep', 'options': [{'channel': channel, 'label': value['label'], 'destination': '***' + value['phone'][-4:]} for channel, value in contacts.items()],
                'company': {'name': company.name if company else 'Your moving team',
                            'color': company.color if company and company.color else company_color}}
    options = []
    if lead.email:
        local, domain = lead.email.split('@', 1)
        options.append({'channel': 'email', 'destination': local[:1]+'***@'+domain})
    if lead.phone: options.append({'channel': 'sms', 'destination': '***'+lead.phone[-4:]})
    return {
        'options': options,
        'link_sms': customer_link_sms_notice(access),
        'company': {
            'name': active_company.name if active_company else 'Your moving team',
            'color': company_color,
        'logo': active_company.logo if active_company else '',
        }
    }


class CodeRequest(BaseModel):
    channel: Literal['sms', 'email', 'rep_sms', 'company_sms']


def deliver_code(lead, channel, code, db: Session):
    message = f'Your moving estimate verification code is {code}. It expires in 10 minutes. Do not share this code.'
    region = setting('AWS_REGION') or 'us-east-1'
    if channel == 'email':
        sender = setting('PUBLIC_MOVE_EMAIL_FROM')
        if not sender: raise HTTPException(503, 'Email verification is not configured. Please contact the moving team.')
        boto3.client('ses', region_name=region).send_email(Source=sender, Destination={'ToAddresses': [lead.email]}, Message={
            'Subject': {'Data': 'Your verification code'}, 'Body': {'Text': {'Data': message}}})
    else:
        # The default supplies a sender only; never assign it to the lead/job.
        company = db.get(Company, lead.company_id) if lead.company_id else db.query(Company).filter(
            Company.is_default_company.is_(True)
        ).one_or_none()
        if company is None:
            raise HTTPException(503, 'No verification SMS sender is configured. Please contact the moving team.')
        number_id = str(company.aircall_number_id or '').strip()
        if not number_id and company.phone:
            number_id = find_number_id(company.phone)
            if number_id:
                db.query(Company).filter(
                    Company.id == company.id,
                    Company.phone == company.phone,
                    func.trim(func.coalesce(Company.aircall_number_id, '')) == '',
                ).update({Company.aircall_number_id: number_id}, synchronize_session='fetch')
                db.commit()
        if not number_id:
            raise HTTPException(503, 'The sending company has no Aircall SMS number configured. Please contact the moving team.')
        # Always pass an explicit number so Aircall cannot use its global default.
        result = send_sms(to=lead.phone, text=message, number_id=number_id, sensitive=True)
        if not result.get('ok'):
            raise HTTPException(502, 'Unable to deliver a code. Please try later or contact your moving team.')


@router.post('/api/public-moves/{access_id}/send-code')
def send_code(body: CodeRequest, access: PublicMoveAccess = Depends(public_access), db: Session = Depends(get_db), request: Request = None):
    access = db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    lead = db.get(Lead, access.lead_id)
    channel = body.channel
    fingerprint = verification_fingerprint(access, db, request)
    if is_rep_request(access, request):
        contacts, _, company = rep_contacts(access, db)
        contact = contacts.get(channel)
        if not contact:
            raise HTTPException(400, 'This rep verification method is unavailable.')
        lead = SimpleNamespace(phone=contact['phone'], email=None, company_id=company.id if company else None)
        channel = 'sms'
    elif channel not in ('sms', 'email'):
        raise HTTPException(400, 'This customer verification method is unavailable.')
    if not (lead.email if channel == 'email' else lead.phone):
        raise HTTPException(400, 'This contact method is unavailable')
    access = verification_state(access, db, request)
    now = NOW()
    if access.otp_sent_at and (now-access.otp_sent_at).total_seconds() < 60: raise HTTPException(429, 'Wait a minute before requesting another code')
    if not access.otp_hour or (now-access.otp_hour).total_seconds() >= 3600:
        access.otp_hour = now; access.otp_sends = 0
    try:
        hourly_limit = int(setting('PUBLIC_MOVE_OTP_HOURLY_LIMIT') or '50')
    except (ValueError, TypeError):
        hourly_limit = 50
    if access.otp_sends >= hourly_limit: raise HTTPException(429, 'Too many codes requested. Please try again in an hour.')
    code = f'{secrets.randbelow(1000000):06d}'
    access.otp_hash = secret_digest(access.id+':'+code); access.otp_expires = now+timedelta(minutes=10)
    access.otp_attempts = 0; access.otp_sent_at = now; access.otp_sends += 1; access.contact_hash = fingerprint
    if channel == 'email':
        # Serialize resends and store only the CRM hash of the emailed code.
        from customer_email_auth import send_email_code
        try:
            send_email_code(lead.email, code, access.id)
        except Exception:
            access.otp_hash = None
            db.commit()
            raise
        db.commit()
    else:
        db.commit()
        try: deliver_code(lead, channel, code, db)
        except HTTPException: raise
        except Exception as exc: raise HTTPException(502, 'Unable to deliver a code. Please try later or contact your moving team.') from exc
    return {'sent': True, 'expires_in': 600, 'resend_after': 60}


class VerifyCode(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')


@router.post('/api/public-moves/{access_id}/verify')
def verify_code(body: VerifyCode, access: PublicMoveAccess = Depends(public_access), db: Session = Depends(get_db), request: Request = None):
    access = db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    link_expires_at = access.expires_at
    fingerprint = verification_fingerprint(access, db, request)
    access = verification_state(access, db, request)
    if not access.otp_hash or not access.otp_expires or access.otp_expires < NOW() or access.otp_attempts >= 5 or access.contact_hash != fingerprint:
        raise HTTPException(400, 'Code expired or unavailable. Request a new code.')
    access.otp_attempts += 1
    if not hmac.compare_digest(access.otp_hash, secret_digest(access.id+':'+body.code)):
        db.commit(); raise HTTPException(400, 'Incorrect code. Please check and try again.')
    access.otp_hash = None
    token = secrets.token_urlsafe(32)
    expires_at = min(link_expires_at, NOW()+timedelta(hours=8))
    db.add(PublicMoveSession(token_hash=digest(token), access_id=access.id, expires_at=expires_at, contact_hash=fingerprint))
    db.commit()
    return {'session': token, 'expires_in': max(0, int((expires_at - NOW()).total_seconds())),
            'expires_at': expires_at.isoformat() + 'Z'}


def _parse_availability_stamps(value: str) -> list[datetime]:
    return [datetime.fromisoformat(stamp.replace('Z', '+00:00')).replace(tzinfo=None) for stamp in re.findall(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z', value)]


def _meeting_move_date_limit(job: LeadJob | None) -> datetime | None:
    if job is None or not job.move_date:
        return None
    try:
        parsed = datetime.strptime(str(job.move_date), '%Y-%m-%d')
    except ValueError:
        return None
    return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)


def _assert_meeting_before_move_date(job: LeadJob | None, stamps: list[datetime], *, label: str = 'Appointment'):
    limit = _meeting_move_date_limit(job)
    if limit is None or not stamps:
        return
    # If the move date on file is already in the past, allow scheduling
    if limit < datetime.utcnow():
        return
    if max(stamps) > limit:
        raise HTTPException(400, f'{label} must be on or before the move date.')


def meeting_dict(row):
    return {'id': row.id, 'status': row.status, 'availability': row.availability or '', 'timezone': row.timezone,
            'scheduled_at': row.scheduled_at.isoformat()+'Z' if row.scheduled_at else None, 'assigned_to': row.assigned_to or '',
            'created_at': row.created_at.isoformat()+'Z' if row.created_at else None}


def _customer_charge_description(name: str, desc: str) -> str:
    if not desc:
        return ''
    text_val = desc.strip()
    # Strip internal bulky matching text / local discount notes
    if 'matched from report' in text_val.lower() or 'bulky item' in text_val.lower():
        match_qty = re.search(r'(\d+(?:\.\d+)?)\s*×', text_val)
        if match_qty and float(match_qty.group(1)) > 1:
            return f'Qty: {float(match_qty.group(1)):g}'
        return ''
    # Simplify travel fee formula notes if present
    if 'estimated mileage including' in text_val.lower() or 'allowance' in text_val.lower():
        miles = [float(m) for m in re.findall(r'(\d+(?:\.\d+)?)\s*miles', text_val)]
        hours_rate = re.search(r'(\d+(?:\.\d+)?)\s*(?:rounded\s+)?hours?\s+at\s+(\$\d+(?:\.\d+)?(?:/hour|/hr)?)', text_val)
        if miles and hours_rate:
            total_m = sum(miles)
            return f'{total_m:.2f} total travel miles ({hours_rate.group(1)} travel hours at {hours_rate.group(2)})'
    # Simplify fuel charge description
    if text_val.lower() in {'flat fuel charge per move', 'flat fuel charge'}:
        return 'Standard fuel surcharge'
    return text_val


@router.get('/api/public-moves/{access_id}/details')
def details(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    return _move_details(access, db)


def _move_details(access, db, *, refresh_report=True):
    from math import ceil
    lead, job = db.get(Lead, access.lead_id), db.get(LeadJob, access.job_id)
    pickup, stops, delivery = _read_job_route(db, job)
    typed = json.loads(job.stop_types or '[]')
    meeting = db.query(WalkthroughRequest).filter_by(job_id=job.id).order_by(WalkthroughRequest.created_at.desc()).first()
    files = move_files(access, db)
    conversation = db.get(LeadLiveSwitch, lead.id)

    # Extract spark report details if available, and auto-process if finished
    spark_info = None
    conv_details = {}
    if conversation and conversation.details:
        try:
            conv_details = json.loads(conversation.details)
            if refresh_report and conv_details.get('pending_spark_payload'):
                from routes.liveswitch import start_ready_report
                start_ready_report(lead.id, db)
                conv_details = json.loads(conversation.details)
            spark_id = conv_details.get("last_spark_id")
            if spark_id:
                if refresh_report and conv_details.get("report_source") != "manual" and not conv_details.get("pending_spark_payload") and (conv_details.get("last_spark_status") not in ("completed", "failed", "cancelled") or conv_details.get("spark_extracted_id") != spark_id):
                    from routes.liveswitch import _api_get, apply_spark_results_to_lead
                    try:
                        remote = _api_get(f"sparks/{spark_id}")
                        db.refresh(conversation, with_for_update=True)
                        conv_details = json.loads(conversation.details)
                        if conv_details.get("last_spark_id") != spark_id:
                            spark_id = conv_details.get("last_spark_id")
                            remote = None
                        if isinstance(remote, dict) and "status" in remote:
                            conv_details["last_spark_status"] = remote.get("status")
                            share_url = remote.get("shareUrl")
                            if share_url:
                                conv_details["last_spark_share_url"] = share_url
                            conversation.details = json.dumps(conv_details)
                            db.commit()
                            if remote.get("status") == "completed" and share_url and conv_details.get("spark_extracted_id") != spark_id:
                                apply_spark_results_to_lead(access.lead_id, share_url, db)
                                # Reload lead and job for updated estimate
                                db.refresh(lead)
                                db.refresh(job)
                                db.refresh(access)
                                db.refresh(conversation)
                                conv_details = json.loads(conversation.details)
                    except Exception:
                        pass
                spark_info = {
                    "id": spark_id,
                    "source": conv_details.get("report_source", "liveswitch"),
                    "status": conv_details.get("last_spark_status", "queued"),
                    "shareUrl": conv_details.get("last_spark_share_url"),
                    "cuft": conv_details.get("spark_extracted_cuft"),
                    "update_error": conv_details.get("notification_error"),
                }
        except Exception:
            pass

    # Resolve estimate: use published estimate if present, otherwise check lead/job price
    # If a spark report is currently pending/running, hide the old estimate until it completes
    estimate = None
    is_spark_pending = bool(spark_info and spark_info.get("status") in ("queued", "running"))
    charges_list = [
        {
            'name': c.name,
            'description': _customer_charge_description(c.name, c.description or ''),
            'total': float(c.total_cost or 0),
            'subtotal': float(c.subtotal or 0),
            'discount_amount': float(c.discount_amount or 0),
            'discount_percent': round(float(c.discount_amount or 0) / float(c.subtotal) * 100, 2) if c.subtotal and c.subtotal > 0 else 0,
        }
        for c in (job.charges or [])
        if (c.total_cost and float(c.total_cost) > 0) or (c.discount_amount and float(c.discount_amount) > 0)
    ]
    report_import_pending = bool(spark_info and conv_details.get('spark_extracted_id') != spark_info['id'])
    if not is_spark_pending and not report_import_pending and conv_details.get('spark_pricing_ready') is not False:
        if access.published_at and access.published_price is not None:
            estimate = {
                'price': str(access.published_price),
                'cuft': str(ceil(access.published_cuft or lead.volume or 0)),
                'charges': charges_list,
            }
        elif job.price is not None and float(job.price) > 0:
            estimate = {
                'price': str(job.price),
                'cuft': str(ceil(lead.volume or 0)),
                'charges': charges_list,
            }
        elif lead.estimated_total:
            try:
                parsed_total = json.loads(lead.estimated_total)
                final_total = float(parsed_total.get('finalTotal') or 0)
                if final_total > 0:
                    estimate = {
                        'price': str(final_total),
                        'cuft': str(ceil(lead.volume or 0)),
                        'charges': charges_list,
                    }
            except Exception:
                pass

    active_company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    company_color = active_company.color if active_company and active_company.color else resolve_company_color(active_company.name if active_company else None, None)
    company_data = {
        'name': active_company.name if active_company else 'Your moving team',
        'phone': active_company.phone or '' if active_company else '',
        'office_address': active_company.office_address or '' if active_company else '',
        'color': company_color,
        'logo': active_company.logo if active_company else '',
    }

    packing_items = []
    packing_package = None
    shuttle = None
    storage = None
    extra_stops = None
    elevator = None
    long_carry = None
    stairs = None
    pricing_pending = json.loads(job.customer_packing_package or '{}').get('pricing_pending', False)
    if pricing_pending:
        estimate = None
    pricing_error = 'Your changes are saved. An updated estimate is pending because pricing is not available for this route yet.' if pricing_pending else ''
    if pricing_pending:
        pricing_error = json.loads(job.customer_packing_package or '{}').get('pricing_save_error') or pricing_error
    if not is_spark_pending and not report_import_pending and (job.company_id or lead.company_id):
        try:
            pricing_options = _customer_pricing_options(lead, job, db)
            packing_package = pricing_options['packing_package']
            packing_items = pricing_options['packing_items']
            shuttle = pricing_options['shuttle']
            storage = pricing_options['storage']
            extra_stops = pricing_options['extra_stops']
            elevator = pricing_options['elevator']
            long_carry = pricing_options['long_carry']
            stairs = pricing_options['stairs']
        except HTTPException as exc:
            if exc.status_code not in (422, 502, 503, 504):
                raise
            pricing_error = pricing_error or 'We could not load pricing options for your address. Your saved details and estimate have not changed. Please retry or contact your moving team.'
    from inventory_questions import questions
    item_questions = questions(active_company, conv_details, db) if spark_info and spark_info.get('status') == 'completed' else []
    from estimate_questions import unanswered_questions
    required_questions = unanswered_questions(dict(extra_stops=extra_stops, elevator=elevator, long_carry=long_carry,
        stairs=stairs, storage=storage, shuttle=shuttle, packing_package=packing_package,
        packing_items=packing_items, item_questions=item_questions),
        package_saved='mode' in json.loads(job.customer_packing_package or '{}'))
    return {'pricing_error': pricing_error, 'extra_stops': extra_stops, 'elevator': elevator, 'long_carry': long_carry, 'stairs': stairs, 'storage': storage, 'shuttle': shuttle, 'google_maps_browser_key': setting('GOOGLE_MAPS_BROWSER_KEY'), 'item_questions': item_questions, 'packing_package': packing_package, 'packing_items': packing_items, 'packing_saved': job.customer_packing is not None, 'name': lead.full_name, 'phone': lead.phone or '', 'email': lead.email or '', 'move_date': job.move_date or '',
            'pickup': pickup, 'delivery': delivery, 'stops': [{'address': s, 'type': typed[i].get('type') if i < len(typed) and typed[i].get('address') == s else None} for i,s in enumerate(stops)],
            'unanswered_questions': required_questions,
            'company': company_data['name'],
            'company_details': company_data,
            'link_sms': customer_link_sms_notice(access),
            'estimate': estimate,
            'spark': spark_info,
            'report_history': report_history(conv_details),
            'editable_files': file_list(files),
            'inventory_draft': conv_details.get('inventory_draft'),
            'list_changed': conv_details.get('inventory_draft', {}).get('body') != conv_details.get('report_list_body'),
            'files_changed': {f.id for f in files} != {row['id'] for row in conv_details.get('report_files', [])},
            'new_file_count': sum(f.id not in {row['id'] for row in conv_details.get('report_files', [])} for f in files) if 'report_files' in conv_details else 0,
            'walkthrough': meeting_dict(meeting) if meeting else None,
            'participant_url': json.loads(conversation.details).get('participantJoinUrl', '') if conversation and meeting and meeting.status == 'scheduled' else '',
            'files': conv_details.get('report_files', [{'id': f.id, 'name': f.file_name, 'size': f.file_size} for f in files])}


@with_job_locations
def _customer_pricing_options(lead, job, db):
    from routes.pricing import (customer_packing_options, customer_packing_package,
                                customer_shuttle, customer_storage, customer_elevator,
                                customer_long_carry, customer_stairs)
    from extra_stops import option as extra_stops_option
    return {
        'packing_package': customer_packing_package(lead, job, db),
        'packing_items': customer_packing_options(lead, job, db),
        'shuttle': customer_shuttle(lead, job, db),
        'storage': customer_storage(lead, job, db),
        'extra_stops': extra_stops_option(lead, job, db),
        'elevator': customer_elevator(lead, job, db),
        'long_carry': customer_long_carry(lead, job, db),
        'stairs': customer_stairs(lead, job, db),
    }


@router.get('/api/public-moves/{access_id}/estimate.pdf')
def download_estimate(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from estimate_pdf import build_estimate_pdf
    data = _move_details(access, db, refresh_report=False)
    from estimate_questions import unanswered_questions
    missing = data.get('unanswered_questions', unanswered_questions(data))
    if missing or data.get('pricing_error'):
        raise HTTPException(409, {'message': 'Answer all required questions before viewing your estimate PDF.', 'unanswered_questions': missing})
    if not data.get('estimate') or not data.get('spark') or data['spark']['status'] != 'completed':
        raise HTTPException(409, 'Your inventory and estimate must be ready before downloading.')
    conversation = db.get(LeadLiveSwitch, access.lead_id)
    state = json.loads(conversation.details) if conversation else {}
    rows = state.get('question_original_rows', state.get('spark_inventory_snapshot', []))
    if not rows:
        raise HTTPException(409, 'There is no inventory to include in this estimate.')
    return Response(build_estimate_pdf(data, rows), media_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="moving-estimate.pdf"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/api/public-moves/{access_id}/reports/{report_id}/select')
def select_customer_report(report_id: str, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from routes.liveswitch import select_spark_report
    result = select_spark_report(access.lead_id, report_id, db)
    if not result.get('ok'):
        raise HTTPException(422, result.get('detail'))
    return result


@router.get('/api/public-moves/{access_id}/inventory-catalog')
def get_customer_inventory_catalog(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    return catalog(db)


@router.post('/api/public-moves/{access_id}/manual-inventory')
def submit_customer_inventory(body: ManualInventoryInput, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    result = save_inventory_draft(body, access, db)
    if not result.get('ok'):
        raise HTTPException(422, result.get('detail'))
    return result


@router.post('/api/public-moves/{access_id}/calculate-price')
def calculate_report_price(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from routes.liveswitch import apply_spark_results_to_lead
    conversation = db.get(LeadLiveSwitch, access.lead_id)
    report = json.loads(conversation.details or '{}') if conversation else {}
    if report.get('last_spark_status') != 'completed' or (report.get('report_source') != 'manual' and not report.get('last_spark_share_url')):
        raise HTTPException(409, 'Your report is not ready yet.')
    result = apply_spark_results_to_lead(access.lead_id, report.get('last_spark_share_url', ''), db)
    if not result.get('ok'):
        raise HTTPException(422, result.get('detail') or 'Could not process the report.')
    if result.get('price') is None:
        raise HTTPException(422, 'The report was imported, but no price could be calculated. Please contact your moving team to check pricing.')
    return result


class CustomerPackageSelection(BaseModel):
    mode: Literal['full', 'partial', 'none'] = 'none'
    unpacking: bool = False
    item_ids: list[str] = Field(default_factory=list, max_length=1000)
    material_item_ids: list[str] | None = Field(default=None, max_length=1000)


class CustomerPackingChange(BaseModel):
    kind: Literal['mode', 'unpacking', 'box', 'bulky', 'shuttle', 'storage', 'stairs', 'long_carry', 'elevator', 'extra_stops']
    location: Literal['pickup', 'delivery'] | None = None
    stops: list[str] = Field(default_factory=list, max_length=100)
    route_origin: str | None = Field(default=None, max_length=500)
    stop_meters: list[int] | None = Field(default=None, max_length=100)

    @field_validator('stop_meters', mode='before')
    @classmethod
    def valid_stop_meters(cls, values):
        if values is not None and (not isinstance(values, list) or any(type(value) is not int or not 0 <= value <= 20000000 for value in values)):
            raise ValueError('Each stop must have a valid driving distance in meters.')
        return values
    has_stops: bool | None = None
    elevator: bool | None = Field(default=None, strict=True)
    carry_feet: int | None = Field(default=None, ge=0, le=100000, strict=True)
    carry_unknown: bool = Field(default=False, strict=True)
    carry_acknowledged: bool = Field(default=False, strict=True)
    flights: int | None = Field(default=None, ge=0, le=1000, strict=True)
    available_date: str = Field(default='', max_length=10)
    revision: str = ''
    item_id: str = ''
    mode: Literal['full', 'partial', 'none'] = 'none'
    enabled: bool = False
    materials: bool | None = None
    service: Literal['packing', 'crating'] | None = None


class CustomerPackingPatch(BaseModel):
    change: CustomerPackingChange | None = None
    package: CustomerPackageSelection | None = None
    selected_ids: list[str] = Field(default_factory=list, max_length=1000)
    selections: dict[str, Literal['packing', 'crating']] = Field(default_factory=dict, max_length=1000)


@router.post('/api/public-moves/{access_id}/packing')
def save_customer_packing(body: CustomerPackingPatch, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from models import LeadJobCharge
    from routes.pricing import customer_packing_options, customer_packing_charge_id
    from routes.leads import _refresh_lead_estimated_total
    job = db.query(LeadJob).filter_by(id=access.job_id, lead_id=access.lead_id).with_for_update().one()
    lead = db.get(Lead, access.lead_id)
    if body.change and body.change.kind == 'extra_stops':
        from extra_stops import option as stops_option, sync_charges
        change=body.change
        if change.location is None or change.has_stops is None:
            raise HTTPException(422,'Choose pickup or delivery and answer Yes or No.')
        addresses=[address.strip() for address in change.stops] if change.has_stops else []
        if any(not address or len(address)>500 for address in addresses) or len(set(a.lower() for a in addresses)) != len(addresses):
            raise HTTPException(422,'Enter a different complete address for each stop.')
        origin=getattr(job,change.location+'_zip') or ''
        if change.stop_meters is not None and (change.route_origin != origin or len(change.stop_meters) != len(addresses)):
            raise HTTPException(409, 'The route changed. Refresh and calculate the stop distances again.')
        if origin.strip().lower() in {a.lower() for a in addresses}:
            raise HTTPException(422,'An extra stop must differ from the main address.')
        pickup,old,delivery=_read_job_route(db,job)
        typed=json.loads(job.stop_types or '[]')
        retained=[{'address':address,'type':typed[i].get('type') if i<len(typed) and typed[i].get('address')==address else None} for i,address in enumerate(old)]
        retained=[row for row in retained if row['type']!=change.location]
        rows=retained+[{'address':address,'type':change.location} for address in addresses]
        rows.sort(key=lambda row: {'pickup':0,None:1,'delivery':2}[row['type']])
        _persist_job_route(db,job.id,pickup,[row['address'] for row in rows],delivery)
        job.stop_types=json.dumps(rows)
        selection=json.loads(job.customer_packing_package or '{}')
        group=selection.setdefault('extra_stops',{}).setdefault(change.location,{})
        group['answer']=change.has_stops
        if change.stop_meters is not None:
            from extra_stops import route_revision
            from uuid import uuid5, NAMESPACE_URL
            group['stops'] = [{'id': str(uuid5(NAMESPACE_URL, f'extra-stop:{job.id}:{change.location}:{address}')),
                               'address': address, 'meters': meters, 'revision': route_revision(origin, address),
                               'distance_source': 'google_browser'}
                              for address, meters in zip(addresses, change.stop_meters)]
        job.customer_packing_package=json.dumps(selection)
        from pricing_save import attempt_pricing
        if selection.get('pricing_pending'):
            from routes.pricing import calculate_and_save_lead_job_price
            def rebuild_price():
                # Missing browser distances must not trigger server routing on a stop edit.
                options = stops_option(lead,job,db,refresh=False)
                if any(row.get('total') is None for group in (options['locations'] if options else []) for row in group['stops']):
                    raise HTTPException(422, 'Stop distances are pending.')
                return calculate_and_save_lead_job_price(lead,job,db)
            attempt_pricing(lead,job,db,rebuild_price,require_price=True)
        else:
            attempt_pricing(lead,job,db,lambda: sync_charges(lead,job,db,refresh=False))
        db.commit()
        return _move_details(access,db,refresh_report=False)
    if body.change and body.change.kind == 'elevator':
        from routes.pricing import customer_elevator, sync_elevator_charges
        change = body.change
        if change.location is None or change.elevator is None:
            raise HTTPException(400, 'Choose Yes or No for elevator use at this address.')
        option = customer_elevator(lead, job, db)
        question = next((row for row in option['locations'] if row['location'] == change.location), None) if option else None
        if not question or question['revision'] != change.revision:
            raise HTTPException(409, 'The address or elevator settings changed. Refresh and answer again.')
        selection = json.loads(job.customer_packing_package or '{}')
        selection.setdefault('elevator', {})[change.location] = {'revision': question['revision'], 'uses_elevator': change.elevator}
        job.customer_packing_package = json.dumps(selection)
        sync_elevator_charges(lead, job, db, change.location)
        db.commit()
        return _move_details(access, db, refresh_report=False)
    if body.change and body.change.kind == 'long_carry':
        from routes.pricing import customer_long_carry, sync_long_carry_charges
        change = body.change
        if change.location is None or (change.carry_unknown and (not change.carry_acknowledged or change.carry_feet is not None)) or (not change.carry_unknown and change.carry_feet is None):
            raise HTTPException(400, 'Enter the carrying distance in feet for this address.')
        option = customer_long_carry(lead, job, db)
        question = next((row for row in option['locations'] if row['location'] == change.location), None) if option else None
        if not question or question['revision'] != change.revision:
            raise HTTPException(409, 'The address or long carry settings changed. Refresh and answer again.')
        selection = json.loads(job.customer_packing_package or '{}')
        selection.setdefault('long_carry', {})[change.location] = {'revision': question['revision'], 'distance_feet': change.carry_feet,
            'unknown': change.carry_unknown, 'acknowledged': change.carry_unknown and change.carry_acknowledged}
        job.customer_packing_package = json.dumps(selection)
        sync_long_carry_charges(lead, job, db, change.location)
        db.commit()
        return _move_details(access, db, refresh_report=False)
    if body.change and body.change.kind == 'stairs':
        from routes.pricing import customer_stairs, sync_stairs_charges
        change = body.change
        if change.location is None or change.flights is None:
            raise HTTPException(400, 'Choose the number of flights for this address, including zero if there are no stairs.')
        option = customer_stairs(lead, job, db)
        question = next((row for row in option['locations'] if row['location'] == change.location), None) if option else None
        if not question or question['revision'] != change.revision:
            raise HTTPException(409, 'The address or stairs settings changed. Refresh and answer again.')
        selection = json.loads(job.customer_packing_package or '{}')
        selection.setdefault('stairs', {})[change.location] = {'revision': question['revision'], 'flights': change.flights}
        job.customer_packing_package = json.dumps(selection)
        sync_stairs_charges(lead, job, db, change.location)
        db.commit()
        return _move_details(access, db, refresh_report=False)
    if body.change and body.change.kind == 'storage':
        from routes.pricing import customer_storage, sync_storage_charge
        from datetime import date
        option = customer_storage(lead, job, db)
        if not option or not option['pickup_date']:
            raise HTTPException(409, 'Confirm the pickup date and storage pricing before choosing a delivery date.')
        try:
            available = date.fromisoformat(body.change.available_date)
        except ValueError:
            raise HTTPException(400, 'Choose a valid earliest delivery date.') from None
        if available.isoformat() < option['pickup_date']:
            raise HTTPException(400, 'Choose a date on or after pickup.')
        selection = json.loads(job.customer_packing_package or '{}')
        selection['storage_date'] = available.isoformat()
        job.customer_packing_package = json.dumps(selection)
        sync_storage_charge(lead, job, db)
        db.commit()
        return _move_details(access, db, refresh_report=False)
    if body.change and body.change.kind == 'shuttle':
        from routes.pricing import customer_shuttle, sync_customer_shuttle_charge
        if 'enabled' not in body.change.model_fields_set:
            raise HTTPException(400, 'Choose an answer for delivery truck access.')
        option = customer_shuttle(lead, job, db)
        if not option or option['automatic'] or body.change.revision != option['revision']:
            raise HTTPException(409, 'Delivery access requirements changed. Refresh your estimate.')
        selection = json.loads(job.customer_packing_package or '{}')
        previous_shuttle = selection.get('shuttle', {})
        selection['shuttle'] = {'answer': body.change.enabled, 'revision': option['revision']}
        if previous_shuttle != selection['shuttle']:
            selection.get('long_carry', {}).pop('delivery', None)
        job.customer_packing_package = json.dumps(selection)
        sync_customer_shuttle_charge(lead, job, db)
        from routes.pricing import sync_long_carry_charges
        sync_long_carry_charges(lead, job, db, 'delivery')
        db.commit()
        return _move_details(access, db, refresh_report=False)
    options = customer_packing_options(lead, job, db)
    change = body.change
    touched = None
    if change:
        stored = json.loads(job.customer_packing or '{}')
        choices = {item_id: 'packing' for item_id in stored} if isinstance(stored, list) else stored
        touched = set()
        if change.kind == 'bulky':
            if change.item_id not in {item['id'] for item in options}:
                raise HTTPException(409, 'This item is no longer available.')
            touched.add(change.item_id)
            if change.service is None:
                choices.pop(change.item_id, None)
            else:
                choices[change.item_id] = change.service
        else:
            selection = json.loads(job.customer_packing_package or '{}')
            if change.kind == 'mode':
                touched.update(['package:full', 'package:partial'])
                touched.update(f'box:{item_id}' for item_id in selection.get('item_ids', []))
                selection['mode'] = change.mode
                if change.mode != 'none':
                    selection['item_ids'] = []
                    selection['material_item_ids'] = []
            elif change.kind == 'unpacking':
                touched.add('package:unpacking')
                selection['unpacking'] = change.enabled
            elif change.kind == 'box':
                if selection.get('mode', 'none') != 'none':
                    raise HTTPException(409, 'Individual boxing is available with no packing selected.')
                touched.add(f'box:{change.item_id}')
                ids = set(selection.get('item_ids', []))
                materials = set(selection.get('material_item_ids', selection.get('item_ids', [])))
                if change.enabled: ids.add(change.item_id)
                else: ids.discard(change.item_id)
                if change.enabled and change.materials is not False: materials.add(change.item_id)
                else: materials.discard(change.item_id)
                selection['item_ids'] = sorted(ids)
                selection['material_item_ids'] = sorted(materials)
            body.package = CustomerPackageSelection(**selection)
    else:
        choices = dict(body.selections)
    for item_id in body.selected_ids:
        choices.setdefault(item_id, 'packing')
    selected = set(choices)
    if not selected.issubset({item['id'] for item in options}):
        raise HTTPException(409, 'Your inventory or pricing changed. Refresh and select your items again.')
    for item in options:
        if item['id'] in choices and choices[item['id']] not in {service['kind'] for service in item['services']}:
            raise HTTPException(409, 'That service is unavailable for this item. Refresh and select again.')
    package_lines = None
    package_old_ids = []
    if body.package is not None:
        from routes.pricing import customer_packing_package, customer_package_lines
        package = customer_packing_package(lead, job, db)
        if package is None:
            raise HTTPException(409, 'Long-distance packing is not available. Refresh your estimate.')
        selection = body.package.model_dump()
        if selection['material_item_ids'] is None:
            selection['material_item_ids'] = list(selection['item_ids'])
        selection['item_ids'] = sorted(set(selection['item_ids']) | set(selection['material_item_ids']))
        if (selection['mode'] != 'none' and selection['mode'] not in package['rates']) or (selection['unpacking'] and 'unpacking' not in package['rates']):
            raise HTTPException(409, 'That packing service is not priced. Refresh your estimate.')
        if not set(selection['item_ids']).issubset({item['id'] for item in package['items']}):
            raise HTTPException(409, 'Your required-box items changed. Refresh your estimate.')
        if selection['mode'] != 'none':
            selection['item_ids'] = []
            selection['material_item_ids'] = []
        previous_package = json.loads(job.customer_packing_package or '{}')
        if 'shuttle' in previous_package:
            selection['shuttle'] = previous_package['shuttle']
        if 'delivery_route' in previous_package:
            selection['delivery_route'] = previous_package['delivery_route']
        if 'storage_date' in previous_package:
            selection['storage_date'] = previous_package['storage_date']
        if 'extra_stops' in previous_package:
            selection['extra_stops'] = previous_package['extra_stops']
        if 'elevator' in previous_package:
            selection['elevator'] = previous_package['elevator']
        if 'long_carry' in previous_package:
            selection['long_carry'] = previous_package['long_carry']
        for key in ('pricing_locations', 'pricing_pending', 'pricing_save_error'):
            if key in previous_package:
                selection[key] = previous_package[key]
        if 'stairs' in previous_package:
            selection['stairs'] = previous_package['stairs']
        package_old_ids = ['package:full', 'package:partial', 'package:unpacking'] + [f'box:{item_id}' for item_id in previous_package.get('item_ids', [])]
        package_lines = customer_package_lines(package, selection)
    if job.price is None:
        # Keep customer choices while the base estimate is still being prepared.
        # Repricing applies these selections when a complete price is available.
        job.customer_packing = json.dumps(choices, sort_keys=True)
        if body.package is not None:
            job.customer_packing_package = json.dumps(selection)
        db.commit()
        return details(access, db)
    previous = set(json.loads(job.customer_packing or '[]'))
    ids = [customer_packing_charge_id(job.id, item_id) for item_id in previous | selected]
    ids.extend(customer_packing_charge_id(job.id, item_id) for item_id in package_old_ids)
    if touched is not None:
        ids = [customer_packing_charge_id(job.id, item_id) for item_id in touched]
    old_rows = db.query(LeadJobCharge).filter(LeadJobCharge.job_id == job.id, LeadJobCharge.id.in_(ids)).all()
    old_total = sum((row.total_cost for row in old_rows), Decimal(0))
    for row in old_rows:
        db.delete(row)
    db.flush()
    new_total = Decimal(0)
    for index, item in enumerate(options):
        if item['id'] in selected and (touched is None or item['id'] in touched):
            service = next(service for service in item['services'] if service['kind'] == choices[item['id']])
            amount = Decimal(str(service['price']))
            db.add(LeadJobCharge(id=customer_packing_charge_id(job.id, item['id']), job_id=job.id,
                                name=f"{item['label']} {choices[item['id']].title()}", description='', sort_order=1000 + index,
                                subtotal=amount, discount_amount=0, total_cost=amount))
            new_total += amount
    if package_lines is not None:
        for index, line in enumerate(package_lines):
            if touched is not None and line['id'] not in touched: continue
            db.add(LeadJobCharge(id=customer_packing_charge_id(job.id, line['id']), job_id=job.id,
                                name=line['name'], description=line['description'], sort_order=2000 + index,
                                subtotal=line['amount'], discount_amount=0, total_cost=line['amount']))
            new_total += line['amount']
        job.customer_packing_package = json.dumps(selection)
    job.customer_packing = json.dumps(choices, sort_keys=True)
    delta = new_total - old_total
    job.price += delta
    for link in db.query(PublicMoveAccess).filter_by(job_id=job.id).all():
        if link.published_price is not None:
            link.published_price += delta
    _refresh_lead_estimated_total(lead.id, db)
    db.commit()
    return details(access, db)


class CustomerAddressSelection(BaseModel):
    proof: str | None = Field(default=None, max_length=4000)
    place_id: str = Field(min_length=1, max_length=300)
    formatted_address: str = Field(min_length=1, max_length=500)
    city: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=2, max_length=3)

    @field_validator('place_id', 'formatted_address', 'city', 'state', 'country')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Select a Google address with a city and state')
        return value.strip()


def selected_customer_address(value, current, selection, label, access_id):
    if value is None or value.strip() == current:
        return current
    if not value.strip():
        raise HTTPException(400, f'Enter a {label.lower()} address.')
    if selection is None:
        # Suggestions enhance this input; provider availability must not block edits.
        return value.strip()
    if selection.formatted_address != value.strip():
        raise HTTPException(400, f'Select a {label.lower()} suggestion with at least a city and state.')
    if selection.place_id == 'manual' and not selection.proof:
        from zip_state import STATE_CODES
        if selection.country != 'US' or selection.state not in STATE_CODES or not selection.formatted_address.endswith(f'{selection.city}, {selection.state}'):
            raise HTTPException(400, 'Enter a city and select a valid state for the manual address.')
        return selection.formatted_address
    from customer_addresses import validate_selection
    validate_selection(selection, access_id)
    return selection.formatted_address


class AddressSearch(BaseModel):
    text: str = Field(min_length=3, max_length=200)
    session_token: str = Field(min_length=16, max_length=36, pattern=r'^[A-Za-z0-9_-]+$')


class AddressResolve(BaseModel):
    place_id: str = Field(min_length=1, max_length=300, pattern=r'^[A-Za-z0-9_-]+$')
    session_token: str = Field(min_length=16, max_length=36, pattern=r'^[A-Za-z0-9_-]+$')


@router.post('/api/public-moves/{access_id}/address-search')
def search_customer_address(body: AddressSearch, response: Response, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    rate(db, 'address-search:' + access.id, limit=60)
    response.headers['Cache-Control'] = 'no-store'
    from customer_addresses import suggestions
    return {'suggestions': suggestions(body.text.strip(), body.session_token)}


@router.post('/api/public-moves/{access_id}/address-resolve')
def resolve_customer_address(body: AddressResolve, response: Response, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    rate(db, 'address-resolve:' + access.id, limit=20)
    response.headers['Cache-Control'] = 'no-store'
    from customer_addresses import resolve_address
    return resolve_address(body.place_id, body.session_token, access.id)


class CustomerPricingLocation(BaseModel):
    address: str = Field(min_length=1, max_length=500)
    state: str
    zip_code: str = Field(default='', pattern=r'^(?:\d{5})?$')
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)

    @field_validator('state')
    @classmethod
    def valid_state(cls, value):
        from zip_state import STATE_CODES
        if value not in STATE_CODES:
            raise ValueError('Unknown US state')
        return value


class CustomerDetailsPatch(BaseModel):
    pricing_locations: list[CustomerPricingLocation] = Field(default_factory=list, max_length=3)
    pickup_place: CustomerAddressSelection | None = None
    delivery_place: CustomerAddressSelection | None = None
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    move_date: str | None = None
    pickup: str | None = Field(default=None, max_length=500)
    delivery: str | None = Field(default=None, max_length=500)

    @field_validator('phone')
    @classmethod
    def phone_number(cls, value):
        if value is None:
            raise ValueError('Phone number is required')
        return normalize_phone(value)

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        return Intake.email_address(value)


@router.patch('/api/public-moves/{access_id}/details')
@router.post('/api/public-moves/{access_id}/details')
def update_customer_details(body: CustomerDetailsPatch, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    lead = db.query(Lead).filter_by(id=access.lead_id).with_for_update().one()
    job = db.query(LeadJob).filter_by(id=access.job_id).with_for_update().one()

    current_pickup, current_stops, current_delivery = _read_job_route(db, job)
    current_move_date = job.move_date
    # Validate route changes before mutating contact or scheduling details.
    addresses = {}
    for field, current in [('pickup', current_pickup), ('delivery', current_delivery)]:
        try:
            addresses[field] = selected_customer_address(getattr(body, field), current, getattr(body, field + '_place'), field.capitalize(), access.id)
        except HTTPException as exc:
            raise HTTPException(exc.status_code, {'field': field, 'message': exc.detail}) from exc
    new_pickup, new_delivery = addresses['pickup'], addresses['delivery']

    if body.name is not None:
        trimmed_name = body.name.strip()
        if trimmed_name:
            lead.full_name = trimmed_name
    if body.phone is not None:
        lead.phone = body.phone
    if 'email' in body.model_fields_set:
        lead.email = body.email

    if body.move_date is not None:
        raw_date = body.move_date.strip()
        if raw_date:
            try:
                parsed_date = datetime.strptime(raw_date[:10], '%Y-%m-%d').date()
                formatted_date = parsed_date.strftime('%Y-%m-%d')
                job.move_date = formatted_date
                # Check that any scheduled meeting is not after this move date
                scheduled = db.query(WalkthroughRequest).filter(
                    WalkthroughRequest.job_id == job.id,
                    WalkthroughRequest.status.in_(['requested', 'scheduled'])
                ).all()
                for req in scheduled:
                    if req.scheduled_at:
                        _assert_meeting_before_move_date(job, [req.scheduled_at], label='Existing appointment')
            except ValueError as e:
                raise HTTPException(400, {'field': 'move_date', 'message': 'Enter a valid move date.'}) from e

    if body.pickup is not None or body.delivery is not None:
        job.pickup_zip = new_pickup
        job.delivery_zip = new_delivery
        _persist_job_route(db, job.id, new_pickup, current_stops, new_delivery)

    pricing_changed = (new_pickup != current_pickup or new_delivery != current_delivery
                       or job.move_date != current_move_date)
    selection = json.loads(job.customer_packing_package or '{}')
    if body.pricing_locations:
        incoming = {row.address.strip().lower(): row.model_dump() for row in body.pricing_locations}
        locations = {row['address'].strip().lower(): row for row in selection.get('pricing_locations', [])}
        locations.update(incoming)
        selection['pricing_locations'] = list(locations.values())[-6:]
        job.customer_packing_package = json.dumps(selection)
    if (pricing_changed or selection.get('pricing_pending')) and (job.price is not None or float(lead.volume or 0) > 0):
        from routes.pricing import calculate_and_save_lead_job_price
        from pricing_save import attempt_pricing
        attempt_pricing(lead,job,db,lambda: calculate_and_save_lead_job_price(lead,job,db),require_price=True)
    db.commit()
    return details(access, db)


@router.get('/api/public-moves/{access_id}/file-preview/{attachment_id}')
def customer_file_preview(attachment_id: str, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    return preview_report_file(access, attachment_id, db)


@router.delete('/api/public-moves/{access_id}/files/{attachment_id}')
def delete_customer_report_file(attachment_id: str, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    return remove_report_file(access, attachment_id, db)


@router.post('/api/public-moves/{access_id}/generate-inventory-report')
def customer_generate_inventory_report(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    # Verify that this customer actually uploaded files
    count = len(move_files(access, db))
    if count == 0:
        saved = db.get(LeadLiveSwitch, access.lead_id)
        details = json.loads(saved.details or '{}') if saved else {}
        draft = details.get('inventory_draft') or {}
        if not draft.get('rows'):
            raise HTTPException(400, 'Add files or items to your list before generating a report.')
        result = submit_inventory(ManualInventoryInput.model_validate(draft['body']), access, db)
        if not result.get('ok'):
            raise HTTPException(422, result.get('detail'))
        return result

    from routes.liveswitch import trigger_lead_spark
    try:
        return trigger_lead_spark(access.lead_id, db=db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Could not generate inventory report: {exc}") from exc


class MeetingBody(BaseModel):
    availability: str = Field(min_length=1, max_length=1000)
    timezone: str = 'America/New_York'

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError('Unknown timezone')
        return value


@router.post('/api/public-moves/{access_id}/walkthrough')
def request_meeting(body: MeetingBody, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    job = db.query(LeadJob).filter_by(id=access.job_id).with_for_update().one()
    available = _parse_availability_stamps(body.availability)
    if available:
        _assert_meeting_before_move_date(job, available, label='Requested appointment')
    existing = db.query(WalkthroughRequest).filter(WalkthroughRequest.job_id == access.job_id, WalkthroughRequest.status.in_(['requested', 'scheduled'])).first()
    if existing: return meeting_dict(existing)
    row = WalkthroughRequest(lead_id=access.lead_id, job_id=access.job_id, availability=body.availability, timezone=body.timezone)
    db.add(row); db.commit(); db.refresh(row)
    return meeting_dict(row)


@router.post('/api/public-moves/{access_id}/reschedule')
def reschedule_meeting(body: MeetingBody, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    job = db.query(LeadJob).filter_by(id=access.job_id).with_for_update().one()
    row = db.query(WalkthroughRequest).filter(WalkthroughRequest.job_id == access.job_id, WalkthroughRequest.status.in_(['requested','scheduled'])).with_for_update().first()
    if not row: raise HTTPException(409, 'This meeting can no longer be rescheduled.')
    stamps = re.findall(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z', body.availability)
    if not stamps: raise HTTPException(400, 'Choose a new appointment window.')
    start = datetime.fromisoformat(stamps[0].replace('Z','+00:00')).replace(tzinfo=None)
    if start <= NOW(): raise HTTPException(400, 'Choose a future appointment window.')
    _assert_meeting_before_move_date(job, [start], label='Requested appointment')
    if window_count(db, start, row.id) >= 4: raise HTTPException(409, 'This time window is full. Choose another time.')
    row.availability = body.availability; row.timezone = body.timezone
    row.status = 'requested'; row.scheduled_at = None; row.updated_at = NOW()
    db.commit()
    return meeting_dict(row)


@router.post('/api/public-moves/{access_id}/files')
def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), x_upload_id: str = Header(min_length=8, max_length=64), access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    access = db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    existing = db.query(PublicMoveUpload).filter_by(access_id=access.id, request_id=x_upload_id).first()
    if existing: return {'id': existing.attachment_id}
    count, size = db.query(func.count(LeadAttachment.id), func.coalesce(func.sum(LeadAttachment.file_size), 0)).join(PublicMoveUpload, LeadAttachment.id == PublicMoveUpload.attachment_id).filter(PublicMoveUpload.access_id == access.id).one()
    content = file.file.read()
    mime = file_type(content, file.filename or '')
    if not mime or not content: raise HTTPException(400, 'Choose a non-empty file.')
    if count >= 200: raise HTTPException(400, 'The upload limit for this move has been reached. Please contact your moving team.')
    name = _safe_attachment_name(file.filename or 'Customer file')
    stored = _upload_attachment_bytes_to_s3(access.lead_id, access.job_id, name, content, mime, 'public_move')
    row = LeadAttachment(lead_id=access.lead_id, job_id=access.job_id, file_name=name, content_type=mime, file_size=len(content), file_blob=b'', external_url=stored, is_external_link=True, external_source='public_move_s3', uploaded_by=None)
    try:
        db.add(row); db.flush(); db.add(PublicMoveUpload(attachment_id=row.id, access_id=access.id, request_id=x_upload_id)); db.commit()
    except Exception:
        db.rollback(); _delete_s3_url(stored); raise
    queue_uploaded_file(access, row.id, db)
    return {'id': row.id}


def staff_access(lead_id, user, db):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    if user.role not in ('admin', 'sales_rep'): raise HTTPException(403, 'Staff access required')
    if user.role == 'sales_rep' and lead.assigned_to != user.id: raise HTTPException(403, 'Only the assigned rep can manage this move')
    db.query(Lead).filter(Lead.id == lead.id).with_for_update().one()
    access = db.query(PublicMoveAccess).filter_by(lead_id=lead.id).with_for_update().first()
    if not access: raise HTTPException(404, 'This lead has no customer page')
    return lead, access


@router.post('/api/leads/{lead_id}/customer-page/rep-session')
def open_rep_session(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, access = staff_access(lead_id, user, db)
    if access.revoked or access.expires_at <= NOW():
        raise HTTPException(403, 'This move link is revoked or expired.')
    token = secrets.token_urlsafe(32)
    expires_at = min(access.expires_at, NOW() + timedelta(hours=8))
    db.add(PublicMoveSession(token_hash=digest(token), access_id=access.id,
                            expires_at=expires_at, contact_hash=rep_contacts(access, db)[1]))
    db.commit()
    return {'url': public_url(access, rep=True), 'access_id': access.id,
            'session': token, 'expires_at': expires_at.isoformat() + 'Z'}


@router.get('/api/leads/{lead_id}/customer-page')
def staff_page(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, access = staff_access(lead_id, user, db)
    job = db.get(LeadJob, access.job_id)
    meetings = db.query(WalkthroughRequest).filter_by(lead_id=lead.id).order_by(WalkthroughRequest.created_at.desc()).all()
    pending = db.query(PublicMoveUpload).filter_by(access_id=access.id, synced_at=None).count()
    return {'url': public_url(access), 'rep_url': public_url(access, rep=True), 'revoked': access.revoked, 'job_id': job.id, 'company_id': lead.company_id or '',
            'price': str(job.price) if job.price is not None else '', 'cuft': str(lead.volume) if lead.volume is not None else '',
            'published': bool(access.published_at), 'pending_uploads': pending, 'requests': [{**meeting_dict(m), 'rep_name': (db.get(User, m.assigned_to).name if m.assigned_to and db.get(User, m.assigned_to) else '')} for m in meetings]}


@router.post('/api/leads/{lead_id}/customer-page/generate')
def generate_customer_page(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = _get_visible_lead_or_404(lead_id, user, db)
    if user.role not in ('admin', 'sales_rep'):
        raise HTTPException(403, 'Staff access required')
    if user.role == 'sales_rep' and lead.assigned_to != user.id:
        raise HTTPException(403, 'Only the assigned rep can manage this move')

    db.query(Lead).filter(Lead.id == lead.id).with_for_update().one()
    access = db.query(PublicMoveAccess).filter_by(lead_id=lead.id).with_for_update().first()
    if access:
        return {'url': public_url(access), 'lead_id': lead.id, 'job_id': access.job_id}

    job = db.query(LeadJob).filter_by(lead_id=lead.id).order_by(LeadJob.job_order.asc()).first()
    if not job:
        raise HTTPException(400, 'Create a job for this lead before generating a customer page')

    access = create_customer_page_access(
        db,
        lead,
        job,
        secret_digest(f'generated:{lead.id}:{job.id}'),
        digest(f'generated:{lead.id}:{job.id}'),
    )
    db.commit()
    return {'url': public_url(access), 'lead_id': lead.id, 'job_id': job.id}


@router.post('/api/leads/{lead_id}/customer-page/sms')
def send_customer_link(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, access = staff_access(lead_id, user, db)
    return deliver_customer_link_sms(lead, access, db)


def customer_link_sms_notice(access):
    if not access.link_sms_sent_at:
        return None
    return {'sent_at': access.link_sms_sent_at.isoformat() + 'Z',
            'phone_last4': access.link_sms_phone_last4 or ''}


def deliver_customer_link_sms(lead, access, db):
    if access.revoked or access.expires_at < NOW(): raise HTTPException(400, 'Customer link is inactive')
    if not lead.phone: raise HTTPException(400, 'This lead has no phone number')
    company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    number = (company.aircall_number_id or '') if company else ''
    if not number and company and company.phone: number = find_number_id(company.phone)
    if not number: raise HTTPException(400, 'Configure an Aircall number for the sending company')
    result = send_sms(to=lead.phone, text=f'View your move, upload files, add an item list, or request a virtual estimate: {public_url(access)}', number_id=number, sensitive=True)
    if not result.get('ok'): raise HTTPException(502, 'Could not send SMS. Please retry.')
    access.link_sms_sent_at = NOW()
    access.link_sms_phone_last4 = re.sub(r'\D', '', lead.phone)[-4:]
    db.commit()
    return {'ok': True}


def deliver_customer_link_email(lead, access, db):
    if not lead.email or not lead.email.strip():
        return {'ok': True, 'skipped': True}
    sender = setting('PUBLIC_MOVE_EMAIL_FROM')
    if not sender:
        raise HTTPException(503, 'Customer email sending is not configured')
    message = f'View your move, upload files, add an item list, or request a virtual estimate: {public_url(access)}'
    try:
        boto3.client('ses', region_name=setting('AWS_REGION') or 'us-east-1').send_email(
            Source=sender, Destination={'ToAddresses': [lead.email.strip()]}, Message={
                'Subject': {'Data': 'Your moving estimate', 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': message, 'Charset': 'UTF-8'}}})
    except Exception:
        raise HTTPException(502, 'Could not send email. Please retry.')
    return {'ok': True}


class SendCustomerLinkRequest(BaseModel):
    dry_run: bool = False


@router.post('/api/leads/{lead_id}/customer-page/send-link')
def send_customer_page_link(lead_id: str, body: SendCustomerLinkRequest,
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, access = staff_access(lead_id, user, db)
    if access.revoked or access.expires_at < NOW():
        raise HTTPException(400, 'Customer link is inactive')
    message = f'View your move, upload files, add an item list, or request a virtual estimate: {public_url(access)}'
    deliveries = []
    for channel, recipient in [('sms', lead.phone), ('email', lead.email)]:
        if recipient and recipient.strip():
            deliveries.append({'channel': channel, 'recipient': recipient.strip(), 'status': 'preview'})
    if not deliveries:
        raise HTTPException(400, 'This customer has no phone number or email address')
    configured_dry_run = (setting('PUBLIC_MOVE_LINK_DRY_RUN') or 'true').strip().lower() != 'false'
    if configured_dry_run or body.dry_run:
        return {'ok': True, 'dry_run': True, 'message': message, 'deliveries': deliveries}
    for delivery in deliveries:
        try:
            if delivery['channel'] == 'sms':
                send_customer_link(lead_id, user, db)
            else:
                deliver_customer_link_email(lead, access, db)
            delivery['status'] = 'sent'
        except HTTPException as exc:
            delivery.update(status='failed', error=str(exc.detail))
        except Exception:
            delivery.update(status='failed', error='The message provider could not send this message.')
    return {'ok': all(row['status'] == 'sent' for row in deliveries), 'dry_run': False, 'deliveries': deliveries}


class StaffPagePatch(BaseModel):
    company_id: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    cuft: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    publish: bool = False
    revoke: bool | None = None


@router.patch('/api/leads/{lead_id}/customer-page')
def update_page(lead_id: str, body: StaffPagePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from math import ceil
    lead, access = staff_access(lead_id, user, db)
    job = db.get(LeadJob, access.job_id)
    if body.company_id is not None:
        if user.role != 'admin': raise HTTPException(403, 'Only administrators can connect a company')
        if body.company_id not in _get_user_company_ids(user, db): raise HTTPException(403, 'Company not available')
        lead.company_id = body.company_id; job.company_id = body.company_id
    if body.price is not None: job.price = body.price
    if body.cuft is not None: lead.volume = Decimal(ceil(body.cuft))
    if body.publish:
        if job.price is None or lead.volume is None or lead.volume <= 0: raise HTTPException(400, 'Enter price and cubic feet before publishing')
        access.published_price = job.price; access.published_cuft = lead.volume; access.published_at = NOW()
    if body.revoke is not None:
        access.revoked = body.revoke
        db.query(PublicMoveSession).filter_by(access_id=access.id).delete()
        access.otp_hash = None
        rep_verification = db.get(PublicMoveRepVerification, access.id)
        if rep_verification:
            rep_verification.otp_hash = None
    db.commit()
    return {'ok': True}


@router.get('/api/walkthrough-requests')
def staff_requests(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    companies = _get_user_company_ids(user, db)
    leads = db.query(Lead).join(PublicMoveAccess, Lead.id == PublicMoveAccess.lead_id).filter(or_(Lead.company_id.in_(companies), Lead.company_id.is_(None))).order_by(Lead.created_at.desc()).all()
    rows = []
    for lead in leads:
        access = db.query(PublicMoveAccess).filter_by(lead_id=lead.id).one()
        meetings = db.query(WalkthroughRequest).filter_by(lead_id=lead.id).order_by(WalkthroughRequest.created_at.desc()).all()
        job = db.get(LeadJob, access.job_id)
        rows.append({'lead_id': lead.id, 'name': lead.full_name, 'company_id': lead.company_id or '',
                     'phone': lead.phone or '', 'pickup': job.pickup_zip if job else lead.pickup_zip,
                     'delivery': job.delivery_zip if job else lead.delivery_zip, 'move_date': job.move_date if job else lead.move_date,
                     'company': lead.company.name if lead.company else 'Unassigned', 'job_id': access.job_id,
                     'requests': [{**meeting_dict(m), 'rep_name': (db.get(User, m.assigned_to).name if m.assigned_to and db.get(User, m.assigned_to) else '')} for m in meetings]})
    return {'items': rows, 'companies': [{'id': c.id, 'name': c.name} for c in db.query(Company).filter(Company.id.in_(companies)).all()],
            'reps': [{'id': u.id, 'name': u.name} for u in db.query(User).filter(User.role.in_(['admin', 'sales_rep'])).all()]}


def window_count(db, start, exclude=None):
    query = db.query(WalkthroughRequest).filter(
        WalkthroughRequest.status == 'scheduled',
        WalkthroughRequest.scheduled_at > start-timedelta(hours=2),
        WalkthroughRequest.scheduled_at < start+timedelta(hours=2))
    if exclude: query = query.filter(WalkthroughRequest.id != exclude)
    return query.count()


class AvailabilityBody(BaseModel):
    starts: list[datetime] = Field(max_length=60)


@router.post('/api/public-moves/{access_id}/availability')
def meeting_availability(body: AvailabilityBody, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    results = []
    for start in body.starts:
        if start.tzinfo is None: raise HTTPException(400, 'Timezone required')
        utc = start.astimezone(timezone.utc).replace(tzinfo=None)
        results.append(utc > NOW() and window_count(db, utc) < 4)
    return {'available': results}


class ScheduleBody(BaseModel):
    status: Literal['requested', 'scheduled', 'completed', 'cancelled'] | None = None
    assigned_to: str | None = None
    scheduled_at: datetime | None = None


@router.patch('/api/walkthrough-requests/{request_id}')
def schedule(request_id: str, body: ScheduleBody, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(WalkthroughRequest, request_id)
    if not row: raise HTTPException(404, 'Request not found')
    staff_access(row.lead_id, user, db)
    if 'assigned_to' in body.model_fields_set:
        if body.assigned_to:
            rep = db.get(User, body.assigned_to)
            if not rep or rep.role not in ('admin', 'sales_rep'): raise HTTPException(400, 'Choose a valid rep')
            row.assigned_to = rep.id
        else:
            row.assigned_to = None
    if body.scheduled_at:
        if body.scheduled_at.tzinfo is None: raise HTTPException(400, 'Scheduled time must include a timezone')
        row.scheduled_at = body.scheduled_at.astimezone(timezone.utc).replace(tzinfo=None)
    elif not row.scheduled_at:
        stamps = _parse_availability_stamps(row.availability)
        if stamps:
            row.scheduled_at = stamps[0]

    target_status = body.status if body.status is not None else row.status
    if target_status == 'scheduled' and not row.assigned_to:
        raise HTTPException(400, 'Choose a rep before approving')
    if target_status == 'scheduled' and not row.scheduled_at:
        raise HTTPException(400, 'No appointment time available to approve')

    if row.scheduled_at is not None:
        job = db.get(LeadJob, row.job_id)
        _assert_meeting_before_move_date(job, [row.scheduled_at], label='Appointment')

    if target_status in ('requested', 'scheduled'):
        db.query(LeadJob).filter_by(id=row.job_id).with_for_update().one()
        duplicate = db.query(WalkthroughRequest).filter(WalkthroughRequest.job_id == row.job_id, WalkthroughRequest.id != row.id, WalkthroughRequest.status.in_(['requested','scheduled'])).first()
        if duplicate: raise HTTPException(409, 'This job already has an active request')

    if target_status == 'scheduled' and row.status != 'scheduled':
        from routes.liveswitch import ensure_conversation
        conversation = ensure_conversation(row.lead_id, user, db)
        if not conversation.get('participantJoinUrl'):
            raise HTTPException(502, 'LiveSwitch did not return a participant link. Please retry approval.')
        # Serialize capacity checks after LiveSwitch's transaction has completed.
        db.execute(text('SELECT pg_advisory_xact_lock(784321901)'))
        if window_count(db, row.scheduled_at, row.id) >= 4:
            raise HTTPException(409, 'This time window is full. Choose another appointment time.')

    row.status = target_status
    db.commit()
    return meeting_dict(row)


@router.delete('/api/leads/{lead_id}/customer-page/files/{attachment_id}')
def delete_staff_report_file(lead_id: str, attachment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, access = staff_access(lead_id, user, db)
    return remove_report_file(access, attachment_id, db)


@router.get('/api/leads/{lead_id}/customer-page/file-preview/{attachment_id}')
def staff_file_preview(lead_id: str, attachment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, access = staff_access(lead_id, user, db)
    return preview_report_file(access, attachment_id, db, all_lead=True)


@router.get('/api/leads/{lead_id}/customer-page/file-download/{attachment_id}')
def staff_file_download(lead_id: str, attachment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, access = staff_access(lead_id, user, db)
    return preview_report_file(access, attachment_id, db, download=True, all_lead=True)


class ImportChatFilesRequest(BaseModel):
    conversation: int = Field(default=0, ge=0)
    cursor: dict | None = None


@router.post('/api/leads/{lead_id}/customer-page/import-chat-files')
def import_chat_files(lead_id: str, body: ImportChatFilesRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from models import CommunicationAssociation
    from db import conversations_table
    from boto3.dynamodb.conditions import Key
    from meta_attachment_archiver import archive_meta_attachments
    lead, access = staff_access(lead_id, user, db)
    conversations = {(row.channel, row.client_identifier, row.company_identifier) for row in db.query(CommunicationAssociation).filter(
        CommunicationAssociation.lead_id == lead_id, CommunicationAssociation.channel.in_(['messenger', 'instagram'])).all()}
    if lead.facebook_user_id and lead.company and lead.company.facebook_page_id:
        for channel in ('messenger', 'instagram'):
            # Explicit links to another lead take precedence over a shared Facebook ID.
            page = lead.company.facebook_page_id
            association = db.query(CommunicationAssociation).filter_by(channel=channel, client_identifier=lead.facebook_user_id, company_identifier=page).first()
            if not association or association.lead_id == lead_id:
                conversations.add((channel, lead.facebook_user_id, page))
    conversations = sorted(conversations)
    if body.conversation >= len(conversations):
        return {'done': True, 'imported': 0, 'failed': 0}
    channel, client, page = conversations[body.conversation]
    params = {'KeyConditionExpression': Key('user_id').eq(client), 'Limit': 1}
    if body.cursor:
        if body.cursor.get('user_id') != client:
            raise HTTPException(400, 'Invalid chat cursor')
        params['ExclusiveStartKey'] = body.cursor
    response = conversations_table.query(**params)
    imported = failed = 0
    for message in response.get('Items', []):
        if str(message.get('page_id', '')) != page or message.get('platform', 'messenger') != channel:
            continue
        message_id = str(message.get('message_id') or '')
        attachments = message.get('attachments') or []
        if not message_id or not isinstance(attachments, list):
            continue
        existing = db.query(LeadAttachment).filter_by(lead_id=lead_id, external_source='meta_s3').all()
        expected = sum(1 for index, item in enumerate(attachments) if isinstance(item, dict)
                       and not any(row.source_external_id == f'{message_id}:{index}' for row in existing))
        imported += archive_meta_attachments(db, lead_id, channel, message_id, attachments)
        db.commit()
        failed += max(0, expected - imported)
    cursor = response.get('LastEvaluatedKey')
    next_conversation = body.conversation if cursor else body.conversation + 1
    return {'done': next_conversation >= len(conversations), 'conversation': next_conversation,
            'cursor': cursor, 'imported': imported, 'failed': failed}


@router.get('/api/leads/{lead_id}/customer-page/sync-status')
def file_sync_status(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, access = staff_access(lead_id, user, db)
    result = sync_status(access.id, db)
    result['editable_files'] = file_list(move_files(access, db, all_lead=True))
    conversation = db.get(LeadLiveSwitch, lead_id)
    details = json.loads(conversation.details or '{}') if conversation else {}
    result['report_file_ids'] = [file['id'] for file in details.get('report_files', [])]
    return result


@router.post('/api/leads/{lead_id}/customer-page/sync-files', status_code=202)
def sync_files(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, access = staff_access(lead_id, user, db)
    return queue_files(access.id, db, actor_id=user.id)


def queue_uploaded_file(access, attachment_id, db):
    conversation = db.get(LeadLiveSwitch, access.lead_id)
    if not conversation or json.loads(conversation.details or '{}').get('last_spark_id'):
        # Stage new files in CRM; never append them to a previous report's conversation.
        return
    try:
        queue_files(access.id, db, attachment_id=attachment_id)
    except Exception:
        db.rollback()
        # Saving a customer file succeeded even if queue submission is unavailable.
        row = db.get(PublicMoveUpload, attachment_id)
        if row and not row.synced_at and row.sync_status not in ('queued', 'syncing'):
            row.sync_status = 'failed'
            row.sync_error = 'File saved in CRM, but sync could not be queued. Please retry.'
            db.commit()

@router.get('/api/leads/{lead_id}/jobs/{job_id}/stop-types')
def get_stop_types(lead_id: str, job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from routes.leads import _get_job_or_404
    job = _get_job_or_404(lead_id, job_id, user, db)
    _, stops, _ = _read_job_route(db, job)
    existing = json.loads(job.stop_types or '[]')
    return {'stops': [{'address': address, 'type': existing[i].get('type') if i < len(existing) and existing[i].get('address') == address else None} for i,address in enumerate(stops)]}


class StopTypesBody(BaseModel):
    stops: list[Stop] = Field(max_length=20)


@router.put('/api/leads/{lead_id}/jobs/{job_id}/stop-types')
def save_stop_types(lead_id: str, job_id: str, body: StopTypesBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from routes.leads import _get_job_or_404, _ensure_not_dispatch_write
    _ensure_not_dispatch_write(user)
    job = _get_job_or_404(lead_id, job_id, user, db)
    _, stops, _ = _read_job_route(db, job)
    if [stop.address for stop in body.stops] != stops: raise HTTPException(409, 'Save the job addresses first, then reload the stop types.')
    job.stop_types = json.dumps([stop.model_dump() for stop in body.stops])
    from extra_stops import sync_charges as sync_extra_stops
    from pricing_save import attempt_pricing
    lead = db.get(Lead,lead_id)
    pricing_error = attempt_pricing(lead,job,db,lambda: sync_extra_stops(lead,job,db))
    db.commit()
    return {'ok': True, 'pricing_error': pricing_error}

class PrepareUpload(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    content_type: str = Field(default='application/octet-stream', max_length=120)


@router.post('/api/public-moves/{access_id}/prepare-upload')
def prepare_upload(body: PrepareUpload, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    completed = db.query(PublicMoveUpload).filter_by(access_id=access.id, request_id=body.request_id).first()
    if completed: return {'completed': True, 'id': completed.attachment_id}
    pending = db.query(PublicMovePendingUpload).filter_by(access_id=access.id, request_id=body.request_id).first()
    count, size = db.query(func.count(LeadAttachment.id), func.coalesce(func.sum(LeadAttachment.file_size), 0)).join(PublicMoveUpload, LeadAttachment.id == PublicMoveUpload.attachment_id).filter(PublicMoveUpload.access_id == access.id).one()
    pending_count, pending_size = db.query(func.count(PublicMovePendingUpload.id), func.coalesce(func.sum(PublicMovePendingUpload.file_size), 0)).filter(PublicMovePendingUpload.access_id == access.id, PublicMovePendingUpload.expires_at > NOW(), PublicMovePendingUpload.request_id != body.request_id).one()
    if count+pending_count >= 200: raise HTTPException(400, 'The upload limit for this move has been reached.')
    if pending and (pending.file_size != body.size or pending.content_type != body.content_type or pending.file_name != _safe_attachment_name(body.name)):
        raise HTTPException(409, 'Upload ID was already used for a different file')
    if not pending:
        pending = PublicMovePendingUpload(access_id=access.id,request_id=body.request_id,object_key=f'public-pending/{access.id}/{uuid4()}',file_name=_safe_attachment_name(body.name),content_type=body.content_type,file_size=body.size)
        db.add(pending)
    pending.expires_at = NOW()+timedelta(minutes=15)
    bucket = os.getenv('ATTACHMENTS_BUCKET', '')
    if not bucket: raise HTTPException(503, 'Upload storage is unavailable')
    signed = boto3.client('s3').generate_presigned_post(Bucket=bucket,Key=pending.object_key,Fields={'Content-Type':body.content_type},
        Conditions=[{'Content-Type':body.content_type},['content-length-range',1,body.size]],ExpiresIn=600)
    db.commit()
    return {'completed':False,'upload':signed}


class FinishUpload(BaseModel):
    request_id: str = Field(min_length=8,max_length=64)


@router.post('/api/public-moves/{access_id}/finish-upload')
def finish_upload(body: FinishUpload, background_tasks: BackgroundTasks, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    done = db.query(PublicMoveUpload).filter_by(access_id=access.id,request_id=body.request_id).first()
    if done: return {'id':done.attachment_id}
    pending = db.query(PublicMovePendingUpload).filter_by(access_id=access.id,request_id=body.request_id).first()
    if not pending or pending.expires_at < NOW(): raise HTTPException(400,'Upload expired. Please try again.')
    bucket = os.getenv('ATTACHMENTS_BUCKET',''); s3=boto3.client('s3')
    try:
        obj=s3.head_object(Bucket=bucket,Key=pending.object_key)
        if obj['ContentLength'] != pending.file_size: raise ValueError('size')
    except ValueError as exc:
        s3.delete_object(Bucket=bucket,Key=pending.object_key)
        raise HTTPException(400,'File content does not match its expected size.') from exc
    except Exception as exc:
        raise HTTPException(502,'The uploaded file could not be verified. Please retry.') from exc
    destination=f'leads/{access.lead_id}/jobs/{access.job_id}/public_move/{uuid4()}/{pending.file_name}'
    s3.copy({'Bucket':bucket,'Key':pending.object_key},bucket,destination,ExtraArgs={'ServerSideEncryption':'AES256'})
    stored=f's3://{bucket}/{destination}'
    row=LeadAttachment(lead_id=access.lead_id,job_id=access.job_id,file_name=pending.file_name,content_type=pending.content_type,file_size=pending.file_size,file_blob=b'',external_url=stored,is_external_link=True,external_source='public_move_s3',uploaded_by=None)
    temporary_key=pending.object_key
    try:
        db.add(row);db.flush();db.add(PublicMoveUpload(attachment_id=row.id,access_id=access.id,request_id=body.request_id));db.delete(pending);db.commit()
    except Exception:
        db.rollback();_delete_s3_url(stored);raise
    try: s3.delete_object(Bucket=bucket,Key=temporary_key)
    except Exception: pass  # Bucket lifecycle removes abandoned staging objects.
    queue_uploaded_file(access,row.id,db)
    return {'id':row.id}


class QuestionImagesRequest(BaseModel):
    names: list[str] = Field(max_length=20)


@router.post('/api/public-moves/{access_id}/question-images')
def customer_question_images(body: QuestionImagesRequest, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from report_question_images import question_images
    conversation = db.query(LeadLiveSwitch).filter_by(lead_id=access.lead_id).with_for_update().first()
    if not conversation:
        return {'images': {}}
    details = json.loads(conversation.details or '{}')
    if details.get('last_spark_status') != 'completed':
        return {'images': {}}
    try:
        images = question_images(details, body.names)
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, 'Reference photos are temporarily unavailable. You can still answer the question.') from exc
    conversation.details = json.dumps(details)
    db.commit()
    return {'images': images}


class ItemAnswerInput(BaseModel):
    report_id: str
    question_id: str
    answer_id: str
    acknowledged: bool = False
    pending: bool = False
    selected_items: list[str] = Field(default_factory=list, max_length=10000)


@router.post('/api/public-moves/{access_id}/item-answer')
def save_item_answer(body: ItemAnswerInput, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from inventory_questions import questions
    from spark_history import remember_report
    from routes.liveswitch import apply_spark_results_to_lead
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=access.lead_id).with_for_update().first()
    state = json.loads(saved.details or '{}') if saved else {}
    if state.get('last_spark_id') != body.report_id or state.get('last_spark_status') != 'completed':
        raise HTTPException(409, 'Your inventory report changed. Refresh before answering.')
    lead = db.get(Lead, access.lead_id)
    company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    current_questions = questions(company, state, db)
    question = next((q for q in current_questions if q['id'] == body.question_id), None)
    if not question: raise HTTPException(409, 'This question changed. Refresh before answering.')
    option = next((a for a in question['answers'] if a['id'] == body.answer_id), None)
    if not option: raise HTTPException(400, 'Choose an available answer')
    selected_items = []
    if question.get('all_items') and option['action'] != 'none':
        available = {item['id'] for item in question['items']}
        selected_items = list(dict.fromkeys(body.selected_items))
        if not set(selected_items).issubset(available):
            raise HTTPException(400, 'Select items from your current inventory')
        if not selected_items and not body.pending:
            raise HTTPException(400, 'Select the items this answer applies to')
    if option.get('acknowledge') and not body.acknowledged and not body.pending: raise HTTPException(400, 'Please acknowledge the item instructions')
    pending = bool((option.get('acknowledge') and not body.acknowledged)
                   or (question.get('all_items') and option['action'] != 'none' and not selected_items))
    # Expand legacy group answers before saving an individual unit.
    state['report_question_answers'] = {q['id']: q['saved'] for q in current_questions if q.get('saved')}
    valid_ids = {q['id'] for q in current_questions}
    state['report_question_answers'] = {k: v for k, v in state.get('report_question_answers', {}).items() if k in valid_ids}
    state['report_question_answers'][question['id']] = {'answer_id': option['id'],
        'name': question['name'], 'room': question['room'], 'question': question['question'], 'answer': option['label'],
        'acknowledged': body.acknowledged, 'pending': pending, 'action': 'pending' if pending else option['action'], 'notice': option['notice'],
        'answered_at': NOW().isoformat() + 'Z'}
    if question.get('all_items'):
        state['report_question_answers'][question['id']]['selected_items'] = selected_items
        state['report_question_answers'][question['id']]['selected_item_labels'] = [
            f"{item['label']} - {item['room']}" if item['room'] else item['label']
            for item in question['items'] if item['id'] in selected_items]
    # Only rebuild inventory and recalculate pricing if shipping actually changes.
    # Pending acknowledgments and informational answers still save immediately.
    from copy import deepcopy
    from inventory_questions import adjusted_inventory
    inventory = state.get('spark_inventory_snapshot', [])
    volume, weight = state.get('spark_extracted_cuft'), state.get('spark_extracted_weight')
    adjusted_rows, adjusted_volume, adjusted_weight = adjusted_inventory(
        company, deepcopy(state), inventory, volume, weight, db)
    inventory_changed = (adjusted_rows != inventory or adjusted_volume != float(volume or 0)
                         or adjusted_weight != float(weight or 0))
    remember_report(state)
    saved.details = json.dumps(state)
    db.commit()
    if not inventory_changed:
        from realtime import publish_customer_update
        publish_customer_update(lead.id)
        return details(access, db)
    result = apply_spark_results_to_lead(lead.id, state.get('last_spark_share_url', ''), db,
        expected_report_id=body.report_id, use_snapshot=True)
    if not result.get('ok'): raise HTTPException(502, result.get('detail', 'Could not update the estimate'))
    return details(access, db)
