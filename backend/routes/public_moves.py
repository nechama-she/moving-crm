"""Verified, job-scoped public access. Staff credentials never enter the public page."""
from spark_history import report_history
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
    access = create_customer_page_access(db, lead, job, key, payload_hash)
    db.commit()
    return {'lead_id': lead.id, 'job_id': job.id, 'url': public_url(access)}


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
        'company': {
            'name': active_company.name if active_company else 'Your moving team',
            'color': company_color,
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
    fingerprint = verification_fingerprint(access, db, request)
    access = verification_state(access, db, request)
    if not access.otp_hash or not access.otp_expires or access.otp_expires < NOW() or access.otp_attempts >= 5 or access.contact_hash != fingerprint:
        raise HTTPException(400, 'Code expired or unavailable. Request a new code.')
    access.otp_attempts += 1
    if not hmac.compare_digest(access.otp_hash, secret_digest(access.id+':'+body.code)):
        db.commit(); raise HTTPException(400, 'Incorrect code. Please check and try again.')
    access.otp_hash = None
    token = secrets.token_urlsafe(32)
    db.add(PublicMoveSession(token_hash=digest(token), access_id=access.id, expires_at=NOW()+timedelta(hours=8), contact_hash=fingerprint))
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
    lead, job = db.get(Lead, access.lead_id), db.get(LeadJob, access.job_id)
    pickup, stops, delivery = _read_job_route(db, job)
    typed = json.loads(job.stop_types or '[]')
    meeting = db.query(WalkthroughRequest).filter_by(job_id=job.id).order_by(WalkthroughRequest.created_at.desc()).first()
    files = db.query(LeadAttachment).filter(LeadAttachment.lead_id == lead.id,
        (LeadAttachment.job_id == access.job_id) | LeadAttachment.job_id.is_(None)).all()
    conversation = db.get(LeadLiveSwitch, lead.id)

    # Extract spark report details if available, and auto-process if finished
    spark_info = None
    conv_details = {}
    if conversation and conversation.details:
        try:
            conv_details = json.loads(conversation.details)
            if conv_details.get('pending_spark_payload'):
                from routes.liveswitch import start_ready_report
                start_ready_report(lead.id, db)
                conv_details = json.loads(conversation.details)
            spark_id = conv_details.get("last_spark_id")
            if spark_id:
                if not conv_details.get("pending_spark_payload") and (conv_details.get("last_spark_status") not in ("completed", "failed", "cancelled") or conv_details.get("spark_extracted_id") != spark_id):
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
                    "status": conv_details.get("last_spark_status", "queued"),
                    "shareUrl": conv_details.get("last_spark_share_url"),
                    "cuft": conv_details.get("spark_extracted_cuft"),
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
        }
        for c in (job.charges or [])
        if c.total_cost and float(c.total_cost) > 0
    ]
    report_import_pending = bool(spark_info and conv_details.get('spark_extracted_id') != spark_info['id'])
    if not is_spark_pending and not report_import_pending and conv_details.get('spark_pricing_ready') is not False:
        if access.published_at and access.published_price is not None:
            estimate = {
                'price': str(access.published_price),
                'cuft': str(access.published_cuft or lead.volume or 0),
                'charges': charges_list,
            }
        elif job.price is not None and float(job.price) > 0:
            estimate = {
                'price': str(job.price),
                'cuft': str(lead.volume or 0),
                'charges': charges_list,
            }
        elif lead.estimated_total:
            try:
                parsed_total = json.loads(lead.estimated_total)
                final_total = float(parsed_total.get('finalTotal') or 0)
                if final_total > 0:
                    estimate = {
                        'price': str(final_total),
                        'cuft': str(lead.volume or 0),
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
    }

    packing_items = []
    packing_package = None
    if not is_spark_pending and not report_import_pending and (job.company_id or lead.company_id):
        from routes.pricing import customer_packing_options, customer_packing_package
        packing_package = customer_packing_package(lead, job, db)
        packing_items = customer_packing_options(lead, job, db)

    return {'packing_package': packing_package, 'packing_items': packing_items, 'packing_saved': job.customer_packing is not None, 'name': lead.full_name, 'phone': lead.phone or '', 'email': lead.email or '', 'move_date': job.move_date or '',
            'pickup': pickup, 'delivery': delivery, 'stops': [{'address': s, 'type': typed[i].get('type') if i < len(typed) and typed[i].get('address') == s else None} for i,s in enumerate(stops)],
            'company': company_data['name'],
            'company_details': company_data,
            'estimate': estimate,
            'spark': spark_info,
            'report_history': report_history(conv_details),
            'new_file_count': sum(f.id not in {row['id'] for row in conv_details.get('report_files', [])} for f in files) if 'report_files' in conv_details else 0,
            'walkthrough': meeting_dict(meeting) if meeting else None,
            'participant_url': json.loads(conversation.details).get('participantJoinUrl', '') if conversation and meeting and meeting.status == 'scheduled' else '',
            'files': conv_details.get('report_files', [{'id': f.id, 'name': f.file_name, 'size': f.file_size} for f in files])}


@router.post('/api/public-moves/{access_id}/reports/{report_id}/select')
def select_customer_report(report_id: str, access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from routes.liveswitch import select_spark_report
    result = select_spark_report(access.lead_id, report_id, db)
    if not result.get('ok'):
        raise HTTPException(422, result.get('detail'))
    return result


@router.post('/api/public-moves/{access_id}/calculate-price')
def calculate_report_price(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from routes.liveswitch import apply_spark_results_to_lead
    conversation = db.get(LeadLiveSwitch, access.lead_id)
    report = json.loads(conversation.details or '{}') if conversation else {}
    if report.get('last_spark_status') != 'completed' or not report.get('last_spark_share_url'):
        raise HTTPException(409, 'Your report is not ready yet.')
    result = apply_spark_results_to_lead(access.lead_id, report['last_spark_share_url'], db)
    if not result.get('ok'):
        raise HTTPException(422, result.get('detail') or 'Could not process the report.')
    if result.get('price') is None:
        raise HTTPException(422, 'The report was imported, but no price could be calculated. Please contact your moving team to check pricing.')
    return result


class CustomerPackageSelection(BaseModel):
    mode: Literal['full', 'partial', 'none'] = 'none'
    unpacking: bool = False
    item_ids: list[str] = Field(default_factory=list, max_length=1000)


class CustomerPackingPatch(BaseModel):
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
    options = customer_packing_options(lead, job, db)
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
        if (selection['mode'] != 'none' and selection['mode'] not in package['rates']) or (selection['unpacking'] and 'unpacking' not in package['rates']):
            raise HTTPException(409, 'That packing service is not priced. Refresh your estimate.')
        if not set(selection['item_ids']).issubset({item['id'] for item in package['items']}):
            raise HTTPException(409, 'Your required-box items changed. Refresh your estimate.')
        if selection['mode'] != 'none':
            selection['item_ids'] = []
        previous_package = json.loads(job.customer_packing_package or '{}')
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
    old_rows = db.query(LeadJobCharge).filter(LeadJobCharge.job_id == job.id, LeadJobCharge.id.in_(ids)).all()
    old_total = sum((row.total_cost for row in old_rows), Decimal(0))
    for row in old_rows:
        db.delete(row)
    db.flush()
    new_total = Decimal(0)
    for index, item in enumerate(options):
        if item['id'] in selected:
            service = next(service for service in item['services'] if service['kind'] == choices[item['id']])
            amount = Decimal(str(service['price']))
            db.add(LeadJobCharge(id=customer_packing_charge_id(job.id, item['id']), job_id=job.id,
                                name=f"{item['label']} {choices[item['id']].title()}", description='', sort_order=1000 + index,
                                subtotal=amount, discount_amount=0, total_cost=amount))
            new_total += amount
    if package_lines is not None:
        for index, line in enumerate(package_lines):
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


class CustomerDetailsPatch(BaseModel):
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
                raise HTTPException(400, 'Invalid move date format (expected YYYY-MM-DD)') from e

    current_pickup, current_stops, current_delivery = _read_job_route(db, job)
    new_pickup = body.pickup.strip() if body.pickup is not None else current_pickup
    new_delivery = body.delivery.strip() if body.delivery is not None else current_delivery
    if body.pickup is not None or body.delivery is not None:
        job.pickup_zip = new_pickup
        job.delivery_zip = new_delivery
        _persist_job_route(db, job.id, new_pickup, current_stops, new_delivery)

    db.commit()
    return details(access, db)


@router.post('/api/public-moves/{access_id}/generate-inventory-report')
def customer_generate_inventory_report(access: PublicMoveAccess = Depends(verified), db: Session = Depends(get_db)):
    from routes.liveswitch import trigger_lead_spark
    # Verify that this customer actually uploaded files
    count = db.query(func.count(LeadAttachment.id)).filter(
        LeadAttachment.lead_id == access.lead_id,
        (LeadAttachment.job_id == access.job_id) | LeadAttachment.job_id.is_(None),
    ).scalar() or 0
    if count == 0:
        raise HTTPException(400, "Please upload photos or videos of your items before generating a report.")

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
    if access.revoked or access.expires_at < NOW(): raise HTTPException(400, 'Customer link is inactive')
    if not lead.phone: raise HTTPException(400, 'This lead has no phone number')
    company = lead.company or db.query(Company).filter(Company.is_default_company.is_(True)).one_or_none()
    number = (company.aircall_number_id or '') if company else ''
    if not number and company and company.phone: number = find_number_id(company.phone)
    if not number: raise HTTPException(400, 'Configure an Aircall number for the sending company')
    result = send_sms(to=lead.phone, text=f'View your move, upload photos, or request a walkthrough: {public_url(access)}', number_id=number, sensitive=True)
    if not result.get('ok'): raise HTTPException(502, 'Could not send SMS. Please retry.')
    return {'ok': True}


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


@router.get('/api/leads/{lead_id}/customer-page/sync-status')
def file_sync_status(lead_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, access = staff_access(lead_id, user, db)
    return sync_status(access.id, db)


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
    job.stop_types = json.dumps([stop.model_dump() for stop in body.stops]); db.commit()
    return {'ok': True}

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
