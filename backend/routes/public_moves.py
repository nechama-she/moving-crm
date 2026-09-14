"""Verified, job-scoped public access. Staff credentials never enter the public page."""
import hmac
import json
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
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
from database import get_db
from libs.aircall.client import find_number_id, send_sms
from models import Lead, LeadJob, Company, User, LeadAttachment, LeadLiveSwitch, PublicMoveAccess, PublicMoveSession, PublicMoveUpload, PublicMoveRate, PublicMovePendingUpload, WalkthroughRequest
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
    if not row or row.revoked or row.expires_at < NOW() or not hmac.compare_digest(row.token_hash, digest(supplied)):
        raise HTTPException(404, 'This link is unavailable or expired. Please contact your moving team.')
    return row


def verified(access: PublicMoveAccess = Depends(public_access), request: Request = None, db: Session = Depends(get_db)):
    session = db.get(PublicMoveSession, digest(request.headers.get('x-public-session', '')))
    lead = db.get(Lead, access.lead_id)
    if not session or session.access_id != access.id or session.expires_at < NOW() or session.contact_hash != contact_fingerprint(lead):
        raise HTTPException(401, 'Please verify your phone or email to continue.')
    return access


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
    phone: str | None = None
    email: str | None = Field(default=None, max_length=254)

    @field_validator('first_name', 'last_name', 'source', 'pickup', 'delivery')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('This field is required')
        return value.strip()

    @field_validator('phone')
    @classmethod
    def phone_number(cls, value):
        return normalize_phone(value) if value else None

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        if not value: return None
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value): raise ValueError('Provide a valid email address')
        return value

    @model_validator(mode='after')
    def contact_required(self):
        if not self.phone and not self.email: raise ValueError('Phone or email is required')
        return self


def public_url(row):
    origin = setting('PUBLIC_MOVE_ORIGIN').rstrip('/')
    if not origin.startswith('https://'):
        raise HTTPException(503, 'The customer website origin is not configured')
    return f'{origin}/move/{row.id}#key={link_token(row.id)}'


@router.post('/api/inventory')
def intake(body: Intake, request: Request, x_api_secret: str = Header(default=''), idempotency_key: str = Header(min_length=8, max_length=128), db: Session = Depends(get_db)):
    expected = setting('PUBLIC_MOVE_API_KEY')
    if not expected or not hmac.compare_digest(expected, x_api_secret): raise HTTPException(401, 'Not authorized')
    rate(db, 'intake:' + digest(expected), 60)
    key = secret_digest('intake:' + idempotency_key)
    # Database transaction lock serializes retries before creating any records.
    from sqlalchemy import text
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int(key[:15], 16)})
    payload_hash = digest(json.dumps(body.model_dump(mode='json'), sort_keys=True))
    existing = db.query(PublicMoveAccess).filter(PublicMoveAccess.key_hash == key).first()
    if existing:
        if existing.request_hash != payload_hash: raise HTTPException(409, 'Idempotency key was already used for different details')
        if existing.revoked or existing.expires_at < NOW(): raise HTTPException(409, 'This request exists but its link has expired or was revoked')
        return {'lead_id': existing.lead_id, 'job_id': existing.job_id, 'url': public_url(existing)}
    if body.company_id and not db.get(Company, body.company_id): raise HTTPException(400, 'Unknown company')
    lead = Lead(full_name=f'{body.first_name} {body.last_name}', company_id=body.company_id, source=body.source,
                phone=body.phone, email=body.email, move_date=body.move_date.isoformat(), pickup_zip=body.pickup, delivery_zip=body.delivery, status='new')
    db.add(lead); db.flush()
    job = LeadJob(lead_id=lead.id, company_id=body.company_id, job_order=1, move_date=body.move_date.isoformat(), pickup_zip=body.pickup, delivery_zip=body.delivery,
                  stop_types=json.dumps([s.model_dump() for s in body.stops]))
    db.add(job); db.flush()
    _persist_job_route(db, job.id, body.pickup, [s.address for s in body.stops], body.delivery)
    access_id = str(uuid4())
    row = PublicMoveAccess(id=access_id, lead_id=lead.id, job_id=job.id, key_hash=key, request_hash=payload_hash,
                           token_hash=digest(link_token(access_id)), expires_at=NOW()+timedelta(days=90))
    url = public_url(row)
    db.add(row); db.commit()
    return {'lead_id': lead.id, 'job_id': job.id, 'url': url}


@router.get('/api/public-moves/{access_id}/verify-options')
def verify_options(access: PublicMoveAccess = Depends(public_access), db: Session = Depends(get_db)):
    lead = db.get(Lead, access.lead_id)
    options = []
    if lead.email:
        local, domain = lead.email.split('@', 1)
        options.append({'channel': 'email', 'destination': local[:1]+'***@'+domain})
    if lead.phone: options.append({'channel': 'sms', 'destination': '***'+lead.phone[-4:]})
    return {'options': options}


class CodeRequest(BaseModel):
    channel: Literal['sms', 'email']


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
def send_code(body: CodeRequest, access: PublicMoveAccess = Depends(public_access), db: Session = Depends(get_db)):
    access = db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    lead = db.get(Lead, access.lead_id)
    if not (lead.email if body.channel == 'email' else lead.phone): raise HTTPException(400, 'This contact method is unavailable')
    now = NOW()
    if access.otp_sent_at and (now-access.otp_sent_at).total_seconds() < 60: raise HTTPException(429, 'Wait a minute before requesting another code')
    if not access.otp_hour or (now-access.otp_hour).total_seconds() >= 3600:
        access.otp_hour = now; access.otp_sends = 0
    if access.otp_sends >= 5: raise HTTPException(429, 'Too many codes requested. Please try again in an hour.')
    code = f'{secrets.randbelow(1000000):06d}'
    access.otp_hash = secret_digest(access.id+':'+code); access.otp_expires = now+timedelta(minutes=10)
    access.otp_attempts = 0; access.otp_sent_at = now; access.otp_sends += 1; access.contact_hash = contact_fingerprint(lead)
    db.commit()
    try: deliver_code(lead, body.channel, code, db)
    except HTTPException: raise
    except Exception as exc: raise HTTPException(502, 'Unable to deliver a code. Please try later or contact your moving team.') from exc
    return {'sent': True, 'expires_in': 600, 'resend_after': 60}


class VerifyCode(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')


@router.post('/api/public-moves/{access_id}/verify')
def verify_code(body: VerifyCode, access: PublicMoveAccess = Depends(public_access), db: Session = Depends(get_db)):
    access = db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    lead = db.get(Lead, access.lead_id)
    if not access.otp_hash or not access.otp_expires or access.otp_expires < NOW() or access.otp_attempts >= 5 or access.contact_hash != contact_fingerprint(lead):
        raise HTTPException(400, 'Code expired or unavailable. Request a new code.')
    access.otp_attempts += 1
    if not hmac.compare_digest(access.otp_hash, secret_digest(access.id+':'+body.code)):
        db.commit(); raise HTTPException(400, 'Incorrect code. Please check and try again.')
    access.otp_hash = None
    token = secrets.token_urlsafe(32)
    db.add(PublicMoveSession(token_hash=digest(token), access_id=access.id, expires_at=NOW()+timedelta(hours=8), contact_hash=contact_fingerprint(lead)))
    db.commit()
    return {'session': token, 'expires_in': 28800}


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
    if max(stamps) > limit:
        raise HTTPException(400, f'{label} must be on or before the move date.')


def meeting_dict(row):
    return {'id': row.id, 'status': row.status, 'availability': row.availability or '', 'timezone': row.timezone,
            'scheduled_at': row.scheduled_at.isoformat()+'Z' if row.scheduled_at else None, 'assigned_to': row.assigned_to or '',
            'created_at': row.created_at.isoformat()+'Z' if row.created_at else None}


@router.get('/api/public-moves/{access_id}/details')
def details(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    lead, job = db.get(Lead, access.lead_id), db.get(LeadJob, access.job_id)
    pickup, stops, delivery = _read_job_route(db, job)
    typed = json.loads(job.stop_types or '[]')
    meeting = db.query(WalkthroughRequest).filter_by(job_id=job.id).order_by(WalkthroughRequest.created_at.desc()).first()
    files = db.query(LeadAttachment).join(PublicMoveUpload, LeadAttachment.id == PublicMoveUpload.attachment_id).filter(PublicMoveUpload.access_id == access.id).all()
    conversation = db.get(LeadLiveSwitch, lead.id)
    return {'name': lead.full_name, 'phone': lead.phone or '', 'email': lead.email or '', 'move_date': job.move_date or '',
            'pickup': pickup, 'delivery': delivery, 'stops': [{'address': s, 'type': typed[i].get('type') if i < len(typed) and typed[i].get('address') == s else None} for i,s in enumerate(stops)],
            'company': lead.company.name if lead.company else 'Your moving team',
            'estimate': {'price': str(access.published_price), 'cuft': str(access.published_cuft)} if access.published_at else None,
            'walkthrough': meeting_dict(meeting) if meeting else None,
            'participant_url': json.loads(conversation.details).get('participantJoinUrl', '') if conversation and meeting and meeting.status == 'scheduled' else '',
            'files': [{'id': f.id, 'name': f.file_name, 'size': f.file_size} for f in files]}


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
    content = file.file.read(100*1024*1024+1)
    mime = file_type(content, file.filename or '')
    if not mime or not content or len(content)>100*1024*1024: raise HTTPException(400, 'Choose a valid file up to 100 MB.')
    if count >= 200 or size+len(content)>500*1024*1024: raise HTTPException(400, 'The upload limit for this move has been reached. Please contact your moving team.')
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
    access = db.query(PublicMoveAccess).filter_by(lead_id=lead.id).first()
    if not access: raise HTTPException(404, 'This lead has no customer page')
    return lead, access


@router.get('/api/leads/{lead_id}/customer-page')
def staff_page(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, access = staff_access(lead_id, user, db)
    job = db.get(LeadJob, access.job_id)
    meetings = db.query(WalkthroughRequest).filter_by(lead_id=lead.id).order_by(WalkthroughRequest.created_at.desc()).all()
    pending = db.query(PublicMoveUpload).filter_by(access_id=access.id, synced_at=None).count()
    return {'url': public_url(access), 'revoked': access.revoked, 'job_id': job.id, 'company_id': lead.company_id or '',
            'price': str(job.price) if job.price is not None else '', 'cuft': str(lead.volume) if lead.volume is not None else '',
            'published': bool(access.published_at), 'pending_uploads': pending, 'requests': [meeting_dict(m) for m in meetings]}


class StaffPagePatch(BaseModel):
    company_id: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    cuft: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    publish: bool = False
    revoke: bool | None = None


@router.patch('/api/leads/{lead_id}/customer-page')
def update_page(lead_id: str, body: StaffPagePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, access = staff_access(lead_id, user, db)
    job = db.get(LeadJob, access.job_id)
    if body.company_id is not None:
        if user.role != 'admin': raise HTTPException(403, 'Only administrators can connect a company')
        if body.company_id not in _get_user_company_ids(user, db): raise HTTPException(403, 'Company not available')
        lead.company_id = body.company_id; job.company_id = body.company_id
    if body.price is not None: job.price = body.price
    if body.cuft is not None: lead.volume = body.cuft
    if body.publish:
        if job.price is None or lead.volume is None or lead.volume <= 0: raise HTTPException(400, 'Enter price and cubic feet before publishing')
        access.published_price = job.price; access.published_cuft = lead.volume; access.published_at = NOW()
    if body.revoke is not None:
        access.revoked = body.revoke
        db.query(PublicMoveSession).filter_by(access_id=access.id).delete()
        access.otp_hash = None
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
                     'requests': [meeting_dict(m) for m in meetings]})
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


@router.get('/api/leads/{lead_id}/customer-page/sync-status')
def file_sync_status(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, access = staff_access(lead_id, user, db)
    return sync_status(access.id, db)


@router.post('/api/leads/{lead_id}/customer-page/sync-files', status_code=202)
def sync_files(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead, access = staff_access(lead_id, user, db)
    return queue_files(access.id, db, actor_id=user.id)


def queue_uploaded_file(access, attachment_id, db):
    if not db.get(LeadLiveSwitch, access.lead_id):
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
    job.stop_types = json.dumps([stop.model_dump() for stop in body.stops]); db.commit()
    return {'ok': True}

class PrepareUpload(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=100*1024*1024)
    content_type: str = Field(default='application/octet-stream', max_length=120)


@router.post('/api/public-moves/{access_id}/prepare-upload')
def prepare_upload(body: PrepareUpload, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    db.query(PublicMoveAccess).filter_by(id=access.id).with_for_update().one()
    completed = db.query(PublicMoveUpload).filter_by(access_id=access.id, request_id=body.request_id).first()
    if completed: return {'completed': True, 'id': completed.attachment_id}
    pending = db.query(PublicMovePendingUpload).filter_by(access_id=access.id, request_id=body.request_id).first()
    count, size = db.query(func.count(LeadAttachment.id), func.coalesce(func.sum(LeadAttachment.file_size), 0)).join(PublicMoveUpload, LeadAttachment.id == PublicMoveUpload.attachment_id).filter(PublicMoveUpload.access_id == access.id).one()
    pending_count, pending_size = db.query(func.count(PublicMovePendingUpload.id), func.coalesce(func.sum(PublicMovePendingUpload.file_size), 0)).filter(PublicMovePendingUpload.access_id == access.id, PublicMovePendingUpload.expires_at > NOW(), PublicMovePendingUpload.request_id != body.request_id).one()
    if count+pending_count >= 200 or size+pending_size+body.size > 500*1024*1024: raise HTTPException(400, 'The upload limit for this move has been reached.')
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
        obj=s3.get_object(Bucket=bucket,Key=pending.object_key)
        if obj['ContentLength'] != pending.file_size: raise ValueError('size')
        stream=obj['Body']
        try: content=stream.read(100*1024*1024+1)
        finally: stream.close()
        if len(content) != pending.file_size: raise ValueError('size')
    except ValueError as exc:
        s3.delete_object(Bucket=bucket,Key=pending.object_key)
        raise HTTPException(400,'File content does not match its expected size.') from exc
    except Exception as exc:
        raise HTTPException(502,'The uploaded file could not be verified. Please retry.') from exc
    stored=_upload_attachment_bytes_to_s3(access.lead_id,access.job_id,pending.file_name,content,pending.content_type,'public_move')
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
