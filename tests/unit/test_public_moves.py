"""Exercise portal access boundaries and OTP lifecycle with an isolated database."""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
if str(BACKEND) not in sys.path: sys.path.insert(0, str(BACKEND))
import models
import sqlalchemy.dialects.postgresql
from public_move_security import digest, secret_digest, link_token, contact_fingerprint, file_type, normalize_phone


@pytest.fixture
def portal(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')
    mocks = {}
    for name in ['auth','config','database','routes.leads']:
        mocks[name] = MagicMock()
    mocks['auth'].get_current_user = lambda: None
    mocks['auth'].require_admin = lambda: None
    mocks['database'].get_db = lambda: None
    mocks['config'].get_config = lambda: {}
    mocks['routes.leads']._safe_attachment_name = lambda name: name
    spec = importlib.util.spec_from_file_location('test_public_moves_module', BACKEND / 'routes/public_moves.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, mocks): spec.loader.exec_module(module)
    from sqlalchemy.pool import StaticPool
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        lead = models.Lead(id='lead-1', full_name='Jane Smith', phone='+12405707987', email='jane@example.com', company_id=None)
        db.add(lead); db.flush()
        job = models.LeadJob(id='job-1', lead_id=lead.id, company_id=None, pickup_zip='Origin', delivery_zip='Destination')
        db.add(job); db.flush()
        access = models.PublicMoveAccess(id='access-1',lead_id=lead.id,job_id=job.id,key_hash='intake',request_hash='payload',token_hash=digest(link_token('access-1')),expires_at=datetime.utcnow()+timedelta(days=1))
        db.add(access); db.commit()
        module.rate = lambda *args, **kwargs: None
        yield module, db, lead, access
    engine.dispose()


def request(link='',session=''):
    return Request({'type':'http','method':'GET','path':'/','headers':[(b'x-public-link',link.encode()),(b'x-public-session',session.encode())], 'client':('127.0.0.1',1234)})


def test_link_does_not_grant_verified_access(portal):
    mod,db,lead,access=portal
    assert mod.public_access(access.id,request(link_token(access.id)),db).id==access.id
    with pytest.raises(HTTPException) as exc: mod.verified(access,request(link_token(access.id)),db)
    assert exc.value.status_code==401


def test_wrong_revoked_and_expired_links_fail(portal):
    mod,db,lead,access=portal
    with pytest.raises(HTTPException): mod.public_access(access.id,request('wrong'),db)
    access.revoked=True; db.commit()
    with pytest.raises(HTTPException): mod.public_access(access.id,request(link_token(access.id)),db)
    access.revoked=False; access.expires_at=datetime.utcnow()-timedelta(seconds=1); db.commit()
    with pytest.raises(HTTPException): mod.public_access(access.id,request(link_token(access.id)),db)


def test_otp_single_use_and_scoped_session(portal):
    mod,db,lead,access=portal
    access.otp_hash=secret_digest(access.id+':123456'); access.otp_expires=datetime.utcnow()+timedelta(minutes=10); access.contact_hash=contact_fingerprint(lead); db.commit()
    result=mod.verify_code(mod.VerifyCode(code='123456'),access,db)
    assert db.get(models.PublicMoveSession,digest(result['session']))
    assert mod.verified(access,request(session=result['session']),db).id==access.id
    with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code='123456'),access,db)
    lead.email='changed@example.com'; db.commit()
    with pytest.raises(HTTPException): mod.verified(access,request(session=result['session']),db)


def test_wrong_code_attempts_lock_challenge(portal):
    mod,db,lead,access=portal
    access.otp_hash=secret_digest(access.id+':123456'); access.otp_expires=datetime.utcnow()+timedelta(minutes=10); access.contact_hash=contact_fingerprint(lead); db.commit()
    for _ in range(5):
        with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code='654321'),access,db)
    with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code='123456'),access,db)
    assert db.query(models.PublicMoveSession).count()==0


def test_resend_limits_and_destination_cannot_be_supplied(portal):
    mod,db,lead,access=portal
    sent=[]; mod.deliver_code=lambda l,c,code,db: sent.append((l.email,c,code))
    mod.send_code(mod.CodeRequest(channel='email'),access,db)
    assert sent[0][0]=='jane@example.com'
    assert sent[0][2] not in access.otp_hash
    with pytest.raises(HTTPException) as exc: mod.send_code(mod.CodeRequest(channel='email'),access,db)
    assert exc.value.status_code==429


def test_intake_contact_and_optional_typed_stops(portal):
    mod,_,_,_=portal
    body=dict(first_name='Jane',last_name='Smith',source='Website',move_date='2026-10-01',pickup='A',delivery='B',stops=[{'address':'C','type':'pickup'},{'address':'D'}])
    with pytest.raises(ValueError): mod.Intake(**body)
    with pytest.raises(ValueError): mod.Intake(**body,email='JANE@example.com')
    parsed=mod.Intake(**body,phone='2405707987',email='JANE@example.com')
    assert parsed.company_id is None and parsed.email=='jane@example.com'
    assert parsed.stops[1].type is None
    with pytest.raises(ValueError): mod.Intake(**body,phone='2405707987',email='bad')


def test_public_details_never_returns_host_link_or_internal_notes(portal):
    mod,db,lead,access=portal
    mod._read_job_route=lambda db,job: ('A',[],'B')
    lead.notes='Secret staff notes'
    db.add(models.LeadLiveSwitch(lead_id=lead.id,details=json.dumps({'hostJoinUrl':'SECRET-HOST','participantJoinUrl':'https://example.com/join'})));db.commit()
    result=mod.details(access,db)
    serialized=json.dumps(result)
    assert 'SECRET-HOST' not in serialized and 'Secret staff notes' not in serialized
    assert result['estimate'] is None


def test_upload_magic_and_phone_normalization():
    assert file_type(b'<script>alert(1)</script>') == 'application/octet-stream'
    assert file_type(b'\xff\xd8\xffrest') == 'image/jpeg'
    assert normalize_phone('(240) 570-7987') == '+12405707987'
    with pytest.raises(ValueError): normalize_phone('123')


def test_http_routes_require_code_before_customer_data(portal):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    mod, db, lead, access = portal
    app = FastAPI(); app.include_router(mod.router)
    app.dependency_overrides[mod.get_db] = lambda: db
    with TestClient(app) as client:
        prefix = f'/api/public-moves/{access.id}'
        headers = {'x-public-link': link_token(access.id)}
        assert client.get(prefix+'/details', headers=headers).status_code == 401
        options = client.get(prefix+'/verify-options', headers=headers)
        assert options.status_code == 200
        assert lead.full_name not in options.text and lead.email not in options.text
        assert client.post(prefix+'/walkthrough', headers=headers, json={'availability':'Tomorrow'}).status_code == 401
        assert db.query(models.WalkthroughRequest).count() == 0


def test_request_is_idempotent_and_estimate_is_published_snapshot(portal):
    mod,db,lead,access=portal
    first=mod.request_meeting(mod.MeetingBody(availability='Monday after 3 pm'),access,db)
    second=mod.request_meeting(mod.MeetingBody(availability='Tuesday'),access,db)
    assert first['id']==second['id']
    assert db.query(models.WalkthroughRequest).count()==1
    mod.staff_access=lambda *args: (lead,access)
    mod._read_job_route=lambda db,job: ('A',[],'B')
    user=SimpleNamespace(role='admin')
    mod.update_page(lead.id,mod.StaffPagePatch(price='1234.50',cuft='500'),user,db)
    assert mod.details(access,db)['estimate'] is None
    mod.update_page(lead.id,mod.StaffPagePatch(publish=True),user,db)
    assert mod.details(access,db)['estimate']=={'price':'1234.50','cuft':'500.00'}
    mod.update_page(lead.id,mod.StaffPagePatch(price='2000'),user,db)
    assert mod.details(access,db)['estimate']['price']=='1234.50'


def test_request_or_approval_cannot_be_after_move_date(portal):
    mod,db,lead,access=portal
    db.get(models.LeadJob, access.job_id).move_date = '2026-10-01'; db.commit()
    with pytest.raises(HTTPException) as exc:
        mod.request_meeting(mod.MeetingBody(availability='2026-10-07T08:00:00Z'), access, db)
    assert exc.value.status_code == 400

    row = models.WalkthroughRequest(id='meeting-1', lead_id=lead.id, job_id=access.job_id, status='requested', availability='2026-10-07T08:00:00Z')
    db.add(models.User(id='rep-1', name='Rep', role='sales_rep', email='rep@example.com', phone='123', password_hash='x'))
    db.add(row); db.commit()
    mod.staff_access = lambda *args: (lead, access)
    with pytest.raises(HTTPException) as exc:
        mod.schedule(row.id, mod.ScheduleBody(status='scheduled', assigned_to='rep-1', scheduled_at=datetime(2026, 10, 7, 8, 0)), SimpleNamespace(role='admin'), db)
    assert exc.value.status_code == 400


def test_otp_expired_and_session_cannot_be_used_for_other_move(portal):
    mod,db,lead,access=portal
    access.otp_hash=secret_digest(access.id+':123456'); access.otp_expires=datetime.utcnow()-timedelta(seconds=1);access.contact_hash=contact_fingerprint(lead);db.commit()
    with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code='123456'),access,db)
    db.add(models.PublicMoveSession(token_hash=digest('other-session'),access_id='another-move',expires_at=datetime.utcnow()+timedelta(hours=1),contact_hash=contact_fingerprint(lead)));db.commit()
    with pytest.raises(HTTPException): mod.verified(access,request(session='other-session'),db)


def test_direct_upload_is_scoped_and_uses_size_bound_signature(portal):
    mod,db,lead,access=portal
    s3=MagicMock();s3.generate_presigned_post.return_value={'url':'https://bucket.s3.amazonaws.com','fields':{'key':'pending'}}
    with patch.object(mod.boto3,'client',return_value=s3), patch.dict(os.environ,{'ATTACHMENTS_BUCKET':'test-bucket'}):
        result=mod.prepare_upload(mod.PrepareUpload(request_id='upload-123',name='room.jpg',size=100,content_type='image/jpeg'),access,db)
    assert result['completed'] is False
    assert ['content-length-range',1,100] in s3.generate_presigned_post.call_args.kwargs['Conditions']
    pending=db.query(models.PublicMovePendingUpload).one()
    assert pending.access_id==access.id and pending.file_size==100
    with pytest.raises(HTTPException):
        mod.prepare_upload(mod.PrepareUpload(request_id='upload-123',name='different.jpg',size=100,content_type='image/jpeg'),access,db)


def test_invalid_staged_file_never_creates_attachment(portal):
    from fastapi import BackgroundTasks
    import io
    mod,db,lead,access=portal
    pending=models.PublicMovePendingUpload(access_id=access.id,request_id='upload-123',object_key='pending',file_name='room.jpg',content_type='image/jpeg',file_size=6,expires_at=datetime.utcnow()+timedelta(minutes=10))
    db.add(pending);db.commit()
    s3=MagicMock();s3.head_object.return_value={'ContentLength':10}
    with patch.object(mod.boto3,'client',return_value=s3), patch.dict(os.environ,{'ATTACHMENTS_BUCKET':'test-bucket'}):
        with pytest.raises(HTTPException) as exc:mod.finish_upload(mod.FinishUpload(request_id='upload-123'),BackgroundTasks(),access,db)
    assert exc.value.status_code==400
    assert db.query(models.LeadAttachment).count()==0
    s3.delete_object.assert_called_once()


def test_global_meeting_window_capacity(portal):
    mod,db,lead,access=portal
    start=datetime.utcnow()+timedelta(days=3)
    for i in range(4):
        db.add(models.WalkthroughRequest(id=f'capacity-{i}',lead_id=lead.id,job_id=access.job_id,status='scheduled',scheduled_at=start))
    db.commit()
    assert mod.window_count(db,start)==4
    assert mod.window_count(db,start+timedelta(hours=2))==0
    assert mod.window_count(db,start,'capacity-0')==3
    db.get(models.WalkthroughRequest,'capacity-0').status='cancelled';db.commit()
    assert mod.window_count(db,start)==3


def test_large_video_upload_has_no_application_size_cap(portal):
    from fastapi import BackgroundTasks
    mod, db, lead, access = portal
    size = 3 * 1024 * 1024 * 1024
    s3 = MagicMock()
    s3.head_object.return_value = {'ContentLength': size}
    with patch.object(mod.boto3, 'client', return_value=s3), patch.dict(os.environ, {'ATTACHMENTS_BUCKET': 'test-bucket'}):
        mod.prepare_upload(mod.PrepareUpload(request_id='large-video', name='video.mov', size=size, content_type='video/quicktime'), access, db)
        result = mod.finish_upload(mod.FinishUpload(request_id='large-video'), BackgroundTasks(), access, db)
        again = mod.finish_upload(mod.FinishUpload(request_id='large-video'), BackgroundTasks(), access, db)
    assert result == again
    assert db.get(models.LeadAttachment, result['id']).file_size == size
    s3.copy.assert_called_once()
    s3.get_object.assert_not_called()


@pytest.mark.parametrize('phone', [None, '', '   ', '123'])
def test_intake_requires_valid_phone_even_with_email(portal, phone):
    mod, _, _, _ = portal
    with pytest.raises(ValueError):
        mod.Intake(first_name='Jane', last_name='Smith', source='Website', move_date='2026-10-01', pickup='A', delivery='B', phone=phone, email='jane@example.com')
    with pytest.raises(ValueError):
        mod.CustomerDetailsPatch(phone=phone)


@pytest.mark.parametrize('email', [None, '', '   '])
def test_phone_only_intake_and_optional_email(portal, email):
    mod, _, _, _ = portal
    body = dict(first_name='Jane', last_name='Smith', source='Website', move_date='2026-10-01', pickup='A', delivery='B', phone='2405707987')
    assert mod.Intake(**body).email is None
    assert mod.Intake(**body, email=email).email is None
    assert mod.CustomerDetailsPatch(email=email).email is None
    assert mod.Intake(**body).phone == '+12405707987'
