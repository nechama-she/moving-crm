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


def test_estimate_pdf_uses_verified_access_and_saved_report_only(portal, monkeypatch):
    module, db, lead, access = portal
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({
        'spark_inventory_snapshot': [{'name': 'Chair', 'amount': 1, 'cuft': 5}]})))
    db.commit()
    calls = []
    def snapshot(actual_access, actual_db, *, refresh_report):
        calls.append((actual_access.id, refresh_report))
        return {'name': lead.full_name, 'estimate': {'price': '100', 'cuft': '5'},
                'spark': {'status': 'completed'}}
    monkeypatch.setattr(module, '_move_details', snapshot)
    response = module.download_estimate(access, db)
    assert response.body.startswith(b'%PDF-')
    assert response.media_type == 'application/pdf'
    assert response.headers['cache-control'] == 'private, no-store'
    assert calls == [(access.id, False)]
    route = next(r for r in module.router.routes if r.path.endswith('/estimate.pdf'))
    assert any(d.call is module.verified for d in route.dependant.dependencies)


def test_estimate_pdf_rejects_pending_estimate(portal, monkeypatch):
    module, db, lead, access = portal
    monkeypatch.setattr(module, '_move_details', lambda *args, **kwargs: {'estimate': None})
    with pytest.raises(HTTPException) as error:
        module.download_estimate(access, db)
    assert error.value.status_code == 409


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
    saved = db.get(models.PublicMoveSession,digest(result['session']))
    assert saved
    assert result['expires_at'] == saved.expires_at.isoformat() + 'Z'
    assert 0 < result['expires_in'] <= 8 * 60 * 60
    assert mod.verified(access,request(session=result['session']),db).id==access.id
    with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code='123456'),access,db)
    lead.email='changed@example.com'; db.commit()
    with pytest.raises(HTTPException): mod.verified(access,request(session=result['session']),db)


def test_verification_session_cannot_outlive_customer_link(portal):
    mod,db,lead,access=portal
    access.expires_at=datetime.utcnow()+timedelta(minutes=30)
    access.otp_hash=secret_digest(access.id+':123456')
    access.otp_expires=datetime.utcnow()+timedelta(minutes=10)
    access.contact_hash=contact_fingerprint(lead)
    db.commit()
    result=mod.verify_code(mod.VerifyCode(code='123456'),access,db)
    saved=db.get(models.PublicMoveSession,digest(result['session']))
    assert saved.expires_at == access.expires_at
    assert result['expires_at'] == access.expires_at.isoformat() + 'Z'


def test_wrong_code_attempts_lock_challenge(portal):
    mod,db,lead,access=portal
    access.otp_hash=secret_digest(access.id+':123456'); access.otp_expires=datetime.utcnow()+timedelta(minutes=10); access.contact_hash=contact_fingerprint(lead); db.commit()
    for _ in range(5):
        with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code='654321'),access,db)
    with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code='123456'),access,db)
    assert db.query(models.PublicMoveSession).count()==0


def test_resend_limits_and_destination_cannot_be_supplied(portal, monkeypatch):
    mod,db,lead,access=portal
    import customer_email_auth
    sent=[]
    def send_email(email, code, access_id):
        sent.append(email)
    monkeypatch.setattr(customer_email_auth, 'send_email_code', send_email)
    mod.send_code(mod.CodeRequest(channel='email'),access,db)
    assert sent == ['jane@example.com']
    assert access.otp_hash
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
    mod.update_page(lead.id,mod.StaffPagePatch(cuft='500'),user,db)
    assert mod.details(access,db)['estimate'] is None
    mod.update_page(lead.id,mod.StaffPagePatch(price='1234.50',publish=True),user,db)
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

@pytest.fixture
def packing_pricing(monkeypatch):
    import ast
    import re
    from decimal import Decimal
    source = (BACKEND / 'routes/pricing.py').read_text(encoding='utf-8')
    names = {'sync_customer_shuttle_charge', 'customer_shuttle', 'add_customer_shuttle_charge', '_service_billable_volume', '_plan_destination_for_delivery', '_normalize_item_name', '_is_bulky_service', '_bulky_item_prices', '_bulky_item_charges',
             '_material_item_names', 'customer_packing_options', 'customer_packing_charge_id', 'add_customer_packing_charges', 'customer_packing_package', 'customer_package_lines', 'add_customer_package_charges', '_packing_service_charges', '_charge_amount'}
    nodes = [n for n in ast.parse(source).body if getattr(n, 'name', '') in names]
    from zip_state import delivery_location
    from local_pricing import match_region_from_address
    from long_distance_packing import packing_card
    import math
    from shuttle import SHUTTLE_PREFIX, shuttle_card, shuttle_option
    scope = {'infer_job_move_type': lambda *args: (None, None), 'PublicMoveAccess': models.PublicMoveAccess, 'SHUTTLE_PREFIX': SHUTTLE_PREFIX, 'shuttle_card': shuttle_card, 'shuttle_option': shuttle_option, 'PricingPlan': object, 'delivery_location': delivery_location, 'match_region_from_address': match_region_from_address, 'PACKING_CARD_PREFIX': '__ld_packing__:', 'packing_card': packing_card, '_rounded_cubic_feet': lambda value: math.ceil(float(value or 0)), 'json': json, 're': re, 'Decimal': Decimal, 'PricingService': object, 'LeadJobCharge': models.LeadJobCharge,
             'BULKY_ITEM_MARKER': '__bulky_item__', 'BULKY_ITEM_PREFIX': '__bulky_item__:',
             '_number': lambda value: Decimal(value) if value else None,
             '_job_spark_inventory_items': lambda *args: []}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<packing-pricing>', 'exec'), scope)
    module = ModuleType('routes.pricing')
    module.__dict__.update(scope)
    monkeypatch.setitem(sys.modules, 'routes.pricing', module)
    return module


def test_packing_options_per_item_and_local_rates(packing_pricing):
    pricing = packing_pricing
    service = SimpleNamespace(id='piano', name='Piano', rate_text='500',
                              comments='__bulky_item__:' + json.dumps({'packing': '120', 'handling': '500'}))
    plan = SimpleNamespace(services=[service])
    job = SimpleNamespace(id='job', customer_packing='["piano:2"]',
                          _estimated_materials_data=lambda: [{'name': 'Piano', 'quantity': 2}, {'name': 'Chair'}])
    items = pricing.customer_packing_options(None, job, None, plan, 'Local')
    assert len(items) == 2
    assert [i['price'] for i in items] == [60, 60]
    assert [i['selected'] for i in items] == [False, True]
    assert items[1]['label'] == 'Piano (2 of 2)'
    assert pricing.customer_packing_options(None, job, None, plan, 'Long Distance')[0]['price'] == 120


def test_shuttle_autosave_preserves_other_charges_and_rejects_stale_answer(portal, packing_pricing, monkeypatch):
    from decimal import Decimal
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    job.delivery_zip = '13544'
    lead.volume = 24
    job.price = access.published_price = Decimal('1000')
    job.customer_packing_package = json.dumps({'mode':'full','unpacking':True,'item_ids':[]})
    db.add(models.LeadJobCharge(id='transport',job_id=job.id,name='Transportation',subtotal=1000,total_cost=1000))
    plan = SimpleNamespace(services=[SimpleNamespace(comments='__delivery_shuttle__:' + json.dumps({
        'enabled':True,'rate':'1.50','access_distance_ft':500,'minimum_cubic_feet':286,'areas':[]}))], rates=[])
    packing_pricing.customer_shuttle.__globals__['infer_job_move_type'] = lambda *args: ('Long Distance',plan)
    monkeypatch.setitem(sys.modules, 'routes.leads', MagicMock())
    monkeypatch.setattr(mod, '_move_details', lambda *args, **kwargs: {'ok':True})
    db.commit()
    revision = packing_pricing.customer_shuttle(lead,job,db)['revision']
    def save(answer, rev=revision):
        return mod.save_customer_packing(mod.CustomerPackingPatch(change=mod.CustomerPackingChange(
            kind='shuttle',enabled=answer,revision=rev)),access,db)
    save(False)
    assert job.price == access.published_price == Decimal('1429')
    save(False)
    assert job.price == Decimal('1429')
    assert db.query(models.LeadJobCharge).count() == 2
    assert json.loads(job.customer_packing_package)['mode'] == 'full'
    save(True)
    assert job.price == access.published_price == Decimal('1000')
    assert db.get(models.LeadJobCharge,'transport').total_cost == 1000
    job.delivery_zip = '10001'
    with pytest.raises(HTTPException) as error:
        save(False)
    assert error.value.status_code == 409
    assert job.price == 1000
    plan.services[0].comments = '__delivery_shuttle__:' + json.dumps({
        'enabled':True,'rate':'2','access_distance_ft':300,'minimum_cubic_feet':286,'areas':[{'state':'NY'}]})
    packing_pricing.sync_customer_shuttle_charge(lead,job,db)
    assert job.price == access.published_price == Decimal('1572')
    db.commit()
    assert db.query(models.LeadJobCharge).count() == 2


def test_packing_save_repeat_remove_and_reject_unknown(portal, packing_pricing, monkeypatch):
    from decimal import Decimal
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    job.price = Decimal('1000')
    access.published_price = Decimal('1000')
    db.add(models.LeadJobCharge(job_id=job.id, name='Transportation', subtotal=1000, total_cost=1000))
    db.commit()
    monkeypatch.setattr(packing_pricing, 'customer_packing_options', lambda *args: [
        {'id': 'piano:1', 'label': 'Piano', 'price': 120, 'services': [{'kind': 'packing', 'price': 120}, {'kind': 'crating', 'price': 300}]}])
    leads = ModuleType('routes.leads')
    leads._refresh_lead_estimated_total = lambda *args: None
    monkeypatch.setitem(sys.modules, 'routes.leads', leads)
    monkeypatch.setattr(mod, 'details', lambda *args: {})
    for _ in range(2):
        mod.save_customer_packing(mod.CustomerPackingPatch(selected_ids=['piano:1']), access, db)
        assert job.price == Decimal('1120')
        assert access.published_price == Decimal('1120')
        assert db.query(models.LeadJobCharge).count() == 2
        assert json.loads(job.customer_packing) == {'piano:1': 'packing'}
    mod.save_customer_packing(mod.CustomerPackingPatch(selections={'piano:1': 'crating'}), access, db)
    assert job.price == Decimal('1300')
    assert access.published_price == Decimal('1300')
    assert db.query(models.LeadJobCharge).filter_by(name='Piano Crating').one().total_cost == Decimal('300')
    assert db.query(models.LeadJobCharge).count() == 2
    with pytest.raises(HTTPException) as exc:
        mod.save_customer_packing(mod.CustomerPackingPatch(selected_ids=['other-job-item']), access, db)
    assert exc.value.status_code == 409
    mod.save_customer_packing(mod.CustomerPackingPatch(selected_ids=[]), access, db)
    assert job.price == Decimal('1000')
    assert access.published_price == Decimal('1000')
    assert db.query(models.LeadJobCharge).one().name == 'Transportation'


@pytest.mark.parametrize('kind,price', [('packing', '60'), ('crating', '150')])
def test_saved_packing_can_be_rebuilt_during_repricing(portal, packing_pricing, kind, price):
    from decimal import Decimal
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    job.estimated_materials = json.dumps([{'name': 'Piano', 'quantity': 2}])
    job.customer_packing = json.dumps({'piano:2': kind})
    service = SimpleNamespace(id='piano', name='Piano', rate_text='500',
                              comments='__bulky_item__:' + json.dumps({'packing': '120', 'crating': '300', 'handling': '500'}))
    plan = SimpleNamespace(services=[service])
    total = packing_pricing.add_customer_packing_charges(lead, job, db, plan, 'Local')
    db.flush()
    assert total == Decimal(price)
    row = db.query(models.LeadJobCharge).one()
    assert row.name == f'Piano (2 of 2) {kind.title()}'
    assert row.total_cost == Decimal(price)
    automatic = packing_pricing._bulky_item_charges([service], ['Piano'])
    assert [c['name'] for c in automatic if c['default_selected']] == ['Piano Handling']


@pytest.mark.parametrize('prices,expected', [
    ({'packing': '120'}, ['packing']),
    ({'crating': '300'}, ['crating']),
    ({'packing': '120', 'crating': '300'}, ['packing', 'crating']),
    ({}, []),
])
def test_packing_and_crating_availability(packing_pricing, prices, expected):
    service = SimpleNamespace(id='piano', name='Piano', rate_text='500',
                              comments='__bulky_item__:' + json.dumps(prices))
    job = SimpleNamespace(id='job', customer_packing='{"piano:1":"crating"}',
                          _estimated_materials_data=lambda: [{'name': 'Piano'}])
    items = packing_pricing.customer_packing_options(None, job, None, SimpleNamespace(services=[service]), 'Local')
    assert ([s['kind'] for s in items[0]['services']] if items else []) == expected
    if 'crating' in expected:
        assert items[0]['selected_service'] == 'crating'
        assert items[0]['price'] == 150
    elif items:
        assert not items[0]['selected']


def test_long_distance_package_inventory_volume_and_materials(portal, packing_pricing):
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    lead.volume = 500.4
    job.estimated_materials = json.dumps([{'name': 'Mirror', 'quantity': 2}, {'name': 'Chair'}])
    service = SimpleNamespace(comments='__ld_packing__:' + json.dumps({
        'full': '2', 'partial': '1', 'unpacking': '.50',
        'items': [{'id': 'mirror', 'name': 'Mirror', 'price': '30'}, {'id': 'tv', 'name': 'TV', 'price': '50'}]}))
    plan = SimpleNamespace(services=[service], rates=[])
    package = packing_pricing.customer_packing_package(lead, job, db, plan, 'Long Distance')
    assert package['cubic_feet'] == 501
    assert package['rates']['full']['total'] == 1002
    assert len(package['items']) == 2
    lines = packing_pricing.customer_package_lines(package, {'mode': 'none', 'unpacking': True, 'item_ids': ['mirror:2']})
    assert [line['name'] for line in lines] == ['Unpacking', 'Mirror (2 of 2) Boxing']
    assert sum(line['amount'] for line in lines) == 280.5
    lines = packing_pricing.customer_package_lines(package, {'mode': 'partial', 'unpacking': True, 'item_ids': ['mirror:2']})
    assert [line['name'] for line in lines] == ['Partial packing', 'Unpacking']
    assert sum(line['amount'] for line in lines) == 751.5
    assert packing_pricing.customer_packing_package(lead, job, db, plan, 'Local') is None
    job.customer_packing_package = json.dumps({'mode': 'partial', 'unpacking': True, 'item_ids': []})
    assert packing_pricing.add_customer_package_charges(lead, job, db, plan, 'Long Distance') == 751.5
    db.flush()
    assert db.query(models.LeadJobCharge).count() == 2


def test_package_save_switch_and_validation(portal, packing_pricing, monkeypatch):
    from decimal import Decimal
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    job.price = Decimal('1000')
    access.published_price = Decimal('1000')
    db.commit()
    package = {'cubic_feet': 500, 'rates': {'full': {'rate': 2, 'total': 1000}, 'unpacking': {'rate': 1, 'total': 500}},
               'items': [{'id': 'mirror:1', 'label': 'Mirror', 'price': 30}]}
    monkeypatch.setattr(packing_pricing, 'customer_packing_options', lambda *args: [])
    monkeypatch.setattr(packing_pricing, 'customer_packing_package', lambda *args: package)
    leads = ModuleType('routes.leads')
    leads._refresh_lead_estimated_total = lambda *args: None
    monkeypatch.setitem(sys.modules, 'routes.leads', leads)
    monkeypatch.setattr(mod, 'details', lambda *args: {})
    for _ in range(2):
        mod.save_customer_packing(mod.CustomerPackingPatch(package={'mode': 'full', 'unpacking': True}), access, db)
        assert job.price == Decimal('2500')
        assert db.query(models.LeadJobCharge).count() == 2
    for selection in [{'mode': 'partial'}, {'mode': 'none', 'item_ids': ['fake']}]:
        with pytest.raises(HTTPException):
            mod.save_customer_packing(mod.CustomerPackingPatch(package=selection), access, db)
        assert job.price == Decimal('2500')
    mod.save_customer_packing(mod.CustomerPackingPatch(package={'mode': 'none', 'item_ids': ['mirror:1']}), access, db)
    assert job.price == Decimal('1030')
    assert access.published_price == Decimal('1030')
    assert db.query(models.LeadJobCharge).one().name == 'Mirror Boxing'
    mod.save_customer_packing(mod.CustomerPackingPatch(package={'mode': 'none'}), access, db)
    assert job.price == Decimal('1000')
    assert db.query(models.LeadJobCharge).count() == 0


def test_packing_card_rejects_invalid_rates_and_items():
    from long_distance_packing import PackingCard
    from pydantic import ValidationError
    for payload in [{'full': '-1'}, {'unpacking': 'NaN'}, {'items': [{'id': 'x', 'name': ' ', 'price': 10}]},
                    {'items': [{'id': 'x', 'name': 'TV', 'price': ''}]}]:
        with pytest.raises(ValidationError):
            PackingCard.model_validate(payload)
    assert PackingCard.model_validate({'full': ''}).full is None


def test_pricing_calculator_uses_configured_cf_rates_once(packing_pricing):
    config = SimpleNamespace(comments='__ld_packing__:' + json.dumps({'full': '2', 'partial': '1', 'unpacking': '.5'}))
    legacy = SimpleNamespace(name='Full packing up to 500', comments='', rate_text='$9 / cf')
    charges = packing_pricing._packing_service_charges([config, legacy], 501, {})
    assert [charge['id'] for charge in charges] == ['packing:full', 'packing:partial', 'packing:unpacking']
    assert [packing_pricing._charge_amount(charge, 501, 1, 0) for charge in charges] == [1002, 501, 250.5]
    assert all(not charge['default_selected'] for charge in charges)


def test_packing_route_uses_customer_session_through_global_auth(portal, packing_pricing, monkeypatch):
    import ast
    import re
    from decimal import Decimal
    from uuid import uuid4
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    mod, db, lead, access = portal
    access.id = str(uuid4())
    access.token_hash = digest(link_token(access.id))
    job = db.get(models.LeadJob, access.job_id)
    job.price = Decimal('1000')
    token = 'verified-customer-session'
    db.add(models.PublicMoveSession(token_hash=digest(token), access_id=access.id,
                                   expires_at=datetime.utcnow() + timedelta(hours=1),
                                   contact_hash=contact_fingerprint(lead)))
    db.commit()
    monkeypatch.setattr(packing_pricing, 'customer_packing_options', lambda *args: [
        {'id': 'piano:1', 'label': 'Piano', 'services': [{'kind': 'crating', 'price': 1500}]}])
    leads = ModuleType('routes.leads')
    leads._refresh_lead_estimated_total = lambda *args: None
    monkeypatch.setitem(sys.modules, 'routes.leads', leads)
    monkeypatch.setattr(mod, 'details', lambda *args: {'saved': True})
    source = ast.parse((BACKEND / 'main.py').read_text(encoding='utf-8'))
    auth = next(node for node in source.body if getattr(node, 'name', '') == 'enforce_authentication')
    scope = {'Request': Request, 're': re, 'HTTPException': HTTPException, 'PUBLIC_PATHS': set()}
    exec(compile(ast.Module(body=[auth], type_ignores=[]), '<global-auth>', 'exec'), scope)
    app = FastAPI(dependencies=[Depends(scope['enforce_authentication'])])
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_db] = lambda: db
    @app.get('/api/staff-only')
    def staff_only():
        return {'staff': True}
    with TestClient(app) as client:
        path = f'/api/public-moves/{access.id}/packing'
        headers = {'x-public-link': link_token(access.id)}
        body = {'selections': {'piano:1': 'crating'}}
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 401
        assert 'verify' in response.json()['detail'].lower()
        headers['x-public-session'] = token
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert job.price == Decimal('2500')
        assert client.post(path, headers=headers, json=body).status_code == 200
        assert job.price == Decimal('2500')
        assert client.get('/api/staff-only', headers=headers).status_code == 401


def test_customer_can_save_inventory_choices_before_base_price(portal, packing_pricing, monkeypatch):
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    assert job.price is None
    monkeypatch.setattr(packing_pricing, 'customer_packing_options', lambda *args: [
        {'id': 'piano:1', 'label': 'Piano', 'services': [{'kind': 'packing', 'price': 500}]}])
    leads = ModuleType('routes.leads')
    leads._refresh_lead_estimated_total = lambda *args: None
    monkeypatch.setitem(sys.modules, 'routes.leads', leads)
    monkeypatch.setattr(mod, 'details', lambda *args: {'estimate': None})
    result = mod.save_customer_packing(mod.CustomerPackingPatch(selections={'piano:1': 'packing'}), access, db)
    assert result['estimate'] is None
    assert json.loads(job.customer_packing) == {'piano:1': 'packing'}
    assert job.price is None
    assert db.query(models.LeadJobCharge).count() == 0


def test_details_exposes_inventory_questions_without_estimate(portal, packing_pricing, monkeypatch):
    mod, db, lead, access = portal
    company = models.Company(id='packing-company', name='Moving company')
    db.add(company)
    job = db.get(models.LeadJob, access.job_id)
    job.company_id = company.id
    db.commit()
    mod._read_job_route = lambda db, job: ('A', [], 'B')
    items = [{'id': 'piano:1', 'label': 'Piano', 'services': [{'kind': 'packing', 'price': 500}]}]
    monkeypatch.setattr(packing_pricing, 'customer_packing_options', lambda *args: items)
    monkeypatch.setattr(packing_pricing, 'customer_packing_package', lambda *args: None)
    result = mod.details(access, db)
    assert result['estimate'] is None
    assert result['packing_items'] == items


@pytest.mark.parametrize('ready,result,status', [
    (True, {'ok': True, 'price': 1250}, 200),
    (False, {'ok': True, 'price': 1250}, 409),
    (True, {'ok': False, 'detail': 'Could not extract volume from report'}, 422),
    (True, {'ok': True, 'price': None}, 422),
])
def test_calculate_price_calls_existing_completion_function(portal, monkeypatch, ready, result, status):
    import ast
    import re
    from uuid import uuid4
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    mod, db, lead, access = portal
    access.id = str(uuid4())
    access.token_hash = digest(link_token(access.id))
    report_url = 'https://example.com/reports/ready-report'
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({
        'last_spark_status': 'completed' if ready else 'running',
        'last_spark_share_url': report_url})))
    token = 'calculation-customer-session'
    db.add(models.PublicMoveSession(token_hash=digest(token), access_id=access.id,
                                   expires_at=datetime.utcnow() + timedelta(hours=1),
                                   contact_hash=contact_fingerprint(lead)))
    db.commit()
    liveswitch = ModuleType('routes.liveswitch')
    liveswitch.apply_spark_results_to_lead = MagicMock(return_value=result)
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', liveswitch)
    source = ast.parse((BACKEND / 'main.py').read_text(encoding='utf-8'))
    auth = next(node for node in source.body if getattr(node, 'name', '') == 'enforce_authentication')
    scope = {'Request': Request, 're': re, 'HTTPException': HTTPException, 'PUBLIC_PATHS': set()}
    exec(compile(ast.Module(body=[auth], type_ignores=[]), '<global-auth>', 'exec'), scope)
    app = FastAPI(dependencies=[Depends(scope['enforce_authentication'])])
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_db] = lambda: db
    with TestClient(app) as client:
        path = f'/api/public-moves/{access.id}/calculate-price'
        headers = {'x-public-link': link_token(access.id)}
        assert client.post(path, headers=headers, json={}).status_code == 401
        liveswitch.apply_spark_results_to_lead.assert_not_called()
        headers['x-public-session'] = token
        response = client.post(path, headers=headers, json={})
        assert response.status_code == status, response.text
        if ready:
            liveswitch.apply_spark_results_to_lead.assert_called_once_with(lead.id, report_url, db)
        else:
            liveswitch.apply_spark_results_to_lead.assert_not_called()


@pytest.fixture
def processing_api():
    import ast
    import re
    import httpx
    from decimal import Decimal
    from spark_processing import SparkProcessingLog
    from spark_history import remember_report, report_history, activate_report
    source = BACKEND / 'routes/liveswitch.py'
    names = {'_safe_float', 'fetch_and_extract_spark_report', 'apply_spark_results_to_lead', 'get_spark_processing', 'select_spark_report', 'get_report_history', 'trigger_lead_spark', 'start_ready_report'}
    nodes = [n for n in ast.parse(source.read_text(encoding='utf-8')).body if getattr(n, 'name', '') in names]
    for node in nodes:
        node.decorator_list = []
        if node.name in ('get_spark_processing', 'get_report_history'):
            node.args.defaults = []
            for arg in node.args.args:
                arg.annotation = None
    scope = {'Lead': models.Lead, 'LeadLiveSwitch': models.LeadLiveSwitch, 'Session': Session,
             'SparkProcessingLog': SparkProcessingLog, 'json': json, 're': re,
             'remember_report': remember_report, 'report_history': report_history, 'activate_report': activate_report,
             'PublicMoveAccess': models.PublicMoveAccess, 'os': os, 'time': __import__('time'),
             'httpx': SimpleNamespace(get=MagicMock()), 'Decimal': Decimal, 'datetime': datetime, 'HTTPException': HTTPException}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    return scope


@pytest.mark.parametrize('failure,failed_step', [('download', 'download'), ('extract', 'extract'), ('pricing', 'pricing'), ('no_price', 'pricing'), ('none', None)])
def test_processing_steps_persist_success_and_failure(portal, processing_api, monkeypatch, failure, failed_step):
    mod, db, lead, access = portal
    api = processing_api
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'report', 'last_spark_status': 'completed'})))
    db.commit()
    payload = {'structuredResult': {'sections': [{'id': 'item-list', 'rows': [
        {'item_name': 'TV', 'quantity': 3, 'unit_volume': 20, 'unit_weight': 0}]}]}}
    if failure == 'extract':
        payload = {'structuredResult': {'sections': []}}
    api['httpx'].get.return_value = SimpleNamespace(status_code=404 if failure == 'download' else 200, json=lambda: payload)
    pricing = ModuleType('routes.pricing')
    def calculate(lead, job, db):
        if failure == 'pricing':
            raise RuntimeError('Missing rate for selected destination')
        if failure == 'no_price':
            return None
        job.price = 750
        return 750
    pricing.calculate_and_save_lead_job_price = calculate
    monkeypatch.setitem(sys.modules, 'routes.pricing', pricing)
    result = api['apply_spark_results_to_lead'](lead.id, 'https://example.com/reports/report', db)
    log = json.loads(db.get(models.LeadLiveSwitch, lead.id).details)['spark_processing']
    assert log['report_id'] == 'report'
    assert log['status'] == ('success' if failure == 'none' else 'error')
    assert len(log['steps']) == 5
    if failed_step:
        step = next(row for row in log['steps'] if row['id'] == failed_step)
        assert step['status'] == 'error'
        assert step['error']
    if failure == 'pricing':
        assert next(row for row in log['steps'] if row['id'] == 'inventory')['status'] == 'rolled_back'
        assert db.query(models.LeadSparkInventoryItem).count() == 0
        assert 'Missing rate' not in json.dumps(result)
    if failure == 'download':
        assert 'HTTP 404' in log['steps'][0]['error']
    if failure == 'none':
        assert result['price'] == 750
        assert all(row['status'] == 'success' for row in log['steps'])
        assert db.query(models.LeadSparkInventoryItem).one().amount == 3


def test_processing_log_stays_out_of_customer_response(portal, processing_api):
    mod, db, lead, access = portal
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'report',
        'last_spark_status': 'completed', 'spark_extracted_id': 'report',
        'spark_processing': {'report_id': 'report', 'status': 'error', 'steps': [{'error': 'STAFF-ONLY-DIAGNOSTIC'}]}})))
    db.commit()
    mod._read_job_route = lambda *args: ('A', [], 'B')
    assert 'STAFF-ONLY-DIAGNOSTIC' not in json.dumps(mod.details(access, db))
    processing_api['_get_visible_lead_or_404'] = lambda *args: lead
    result = processing_api['get_spark_processing'](lead.id, object(), db)
    assert result['processing']['steps'][0]['error'] == 'STAFF-ONLY-DIAGNOSTIC'


def test_processing_errors_redact_credentials():
    from spark_processing import error_detail
    message = error_detail(RuntimeError('token=secretvalue password=private Bearer accessvalue https://example.com/path?key=value'))
    assert all(value not in message for value in ('secretvalue', 'private', 'accessvalue', 'key=value'))


def test_processing_log_requires_visible_lead(portal, processing_api):
    mod, db, lead, access = portal
    def deny(*args):
        raise HTTPException(404, 'Lead not found')
    processing_api['_get_visible_lead_or_404'] = deny
    with pytest.raises(HTTPException) as exc:
        processing_api['get_spark_processing'](lead.id, object(), db)
    assert exc.value.status_code == 404


def test_selecting_history_reimports_and_reprices(portal, processing_api, monkeypatch):
    from spark_history import remember_report, report_history
    mod, db, lead, access = portal
    report = {'last_spark_id': 'older', 'last_spark_status': 'completed', 'last_spark_at': 100,
              'last_spark_share_url': 'https://example.com/reports/older', 'spark_extracted_id': 'older'}
    remember_report(report)
    report.update(last_spark_id='newer', last_spark_at=200,
                  last_spark_share_url='https://example.com/reports/newer', spark_extracted_id='newer')
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps(report)))
    db.commit()
    pricing = ModuleType('routes.pricing')
    def calculate(lead, job, db):
        job.price = float(lead.volume) * 10
        return job.price
    pricing.calculate_and_save_lead_job_price = calculate
    monkeypatch.setitem(sys.modules, 'routes.pricing', pricing)
    payload = {'structuredResult': {'sections': [{'id': 'item-list', 'rows': [
        {'item_name': 'TV', 'quantity': 2, 'unit_volume': 20}]}]}}
    processing_api['httpx'].get.return_value = SimpleNamespace(status_code=200, json=lambda: payload)
    result = processing_api['select_spark_report'](lead.id, 'older', db)
    assert result['ok'] and result['price'] == 400
    assert float(lead.volume) == 40
    assert float(access.published_price) == 400
    assert db.query(models.LeadSparkInventoryItem).one().amount == 2
    reports = report_history(json.loads(db.get(models.LeadLiveSwitch, lead.id).details))
    assert [row['id'] for row in reports] == ['newer', 'older']
    assert [row['id'] for row in reports if row['current']] == ['older']
    assert reports[1]['inventory'][0]['name'] == 'TV'
    # Invalid / foreign report IDs cannot change this lead's active report.
    with pytest.raises(HTTPException) as exc:
        processing_api['select_spark_report'](lead.id, 'another-leads-report', db)
    assert exc.value.status_code == 409
    assert json.loads(db.get(models.LeadLiveSwitch, lead.id).details)['last_spark_id'] == 'older'


def test_history_requires_visible_lead(portal, processing_api):
    mod, db, lead, access = portal
    def deny(*args):
        raise HTTPException(404, 'Lead not found')
    processing_api['_get_visible_lead_or_404'] = deny
    with pytest.raises(HTTPException):
        processing_api['get_report_history'](lead.id, object(), db)


def test_history_selection_is_blocked_while_new_run_is_pending(portal, processing_api):
    mod, db, lead, access = portal
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'new', 'last_spark_status': 'running'})))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        processing_api['select_spark_report'](lead.id, 'old', db)
    assert exc.value.status_code == 409
    processing_api['httpx'].get.assert_not_called()


@pytest.mark.parametrize('authenticated', [False, True])
def test_customer_report_selection_uses_verified_route(portal, monkeypatch, authenticated):
    import ast
    import re
    from uuid import uuid4
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    mod, db, lead, access = portal
    access.id = str(uuid4())
    access.token_hash = digest(link_token(access.id))
    token = 'history-session'
    db.add(models.PublicMoveSession(token_hash=digest(token), access_id=access.id,
        expires_at=datetime.utcnow() + timedelta(hours=1), contact_hash=contact_fingerprint(lead)))
    db.commit()
    liveswitch = ModuleType('routes.liveswitch')
    liveswitch.select_spark_report = MagicMock(return_value={'ok': True, 'price': 400})
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', liveswitch)
    source = ast.parse((BACKEND / 'main.py').read_text(encoding='utf-8'))
    node = next(node for node in source.body if getattr(node, 'name', '') == 'enforce_authentication')
    scope = {'Request': Request, 're': re, 'HTTPException': HTTPException, 'PUBLIC_PATHS': set()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<global-auth>', 'exec'), scope)
    app = FastAPI(dependencies=[Depends(scope['enforce_authentication'])])
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_db] = lambda: db
    with TestClient(app) as client:
        headers = {'x-public-link': link_token(access.id)}
        if authenticated:
            headers['x-public-session'] = token
        response = client.post(f'/api/public-moves/{access.id}/reports/older/select', json={}, headers=headers)
        assert response.status_code == (200 if authenticated else 401), response.text
    if authenticated:
        liveswitch.select_spark_report.assert_called_once_with(lead.id, 'older', db)
    else:
        liveswitch.select_spark_report.assert_not_called()


def test_old_import_cannot_replace_a_new_current_report(portal, processing_api):
    mod, db, lead, access = portal
    saved = models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'old', 'last_spark_status': 'completed'}))
    db.add(saved)
    db.commit()
    original_volume = lead.volume
    def download(*args, **kwargs):
        # Simulate a new report starting while the old HTTP request is in flight.
        saved.details = json.dumps({'last_spark_id': 'new', 'last_spark_status': 'queued'})
        db.commit()
        return SimpleNamespace(status_code=200, json=lambda: {'structuredResult': {'sections': [
            {'id': 'item-list', 'rows': [{'item_name': 'TV', 'quantity': 1, 'unit_volume': 20}]}]}})
    processing_api['httpx'].get.side_effect = download
    result = processing_api['apply_spark_results_to_lead'](lead.id, 'https://example.com/reports/old', db)
    assert result['ok'] is False
    assert json.loads(saved.details)['last_spark_id'] == 'new'
    assert lead.volume == original_volume
    assert db.query(models.LeadSparkInventoryItem).count() == 0


def test_pending_report_selection_hides_previous_estimate(portal, monkeypatch):
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    job.price = 999
    access.published_price = 999
    access.published_at = datetime.utcnow()
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'selected',
        'last_spark_status': 'completed', 'spark_pricing_ready': False})))
    db.commit()
    mod._read_job_route = lambda *args: ('A', [], 'B')
    liveswitch = ModuleType('routes.liveswitch')
    liveswitch._api_get = MagicMock(side_effect=RuntimeError('offline'))
    liveswitch.apply_spark_results_to_lead = MagicMock()
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', liveswitch)
    result = mod.details(access, db)
    assert result['estimate'] is None
    assert result['report_history'][0]['current']


@pytest.fixture
def rep_portal(portal):
    mod, db, lead, access = portal
    company = models.Company(id='rep-company', name='Move Company', phone='+12405550111')
    rep = models.User(id='assigned-rep', name='Assigned Rep', email='rep@example.com',
                      phone='+12405550222', password_hash='unused')
    db.add_all([company, rep])
    lead.company_id = company.id
    lead.assigned_to = rep.id
    db.commit()
    return mod, db, lead, access, rep, company


def test_rep_link_options_are_only_rep_and_company(rep_portal):
    mod, db, lead, access, rep, company = rep_portal
    rep_request = request(mod.rep_link_token(access))
    assert mod.public_access(access.id, rep_request, db).id == access.id
    options = mod.verify_options(access, db, rep_request)
    assert options['audience'] == 'rep'
    assert options['options'] == [
        {'channel': 'rep_sms', 'label': 'Assigned rep', 'destination': '***0222'},
        {'channel': 'company_sms', 'label': 'Company phone', 'destination': '***0111'}]
    assert {r['channel'] for r in mod.verify_options(access, db)['options']} == {'sms', 'email'}
    access.revoked = True
    db.commit()
    with pytest.raises(HTTPException):
        mod.public_access(access.id, rep_request, db)


@pytest.mark.parametrize('channel,phone', [('rep_sms', '+12405550222'), ('company_sms', '+12405550111')])
def test_rep_code_goes_to_saved_phone_and_sessions_are_separate(rep_portal, channel, phone):
    mod, db, lead, access, rep, company = rep_portal
    rep_request = request(mod.rep_link_token(access))
    sent = []
    mod.deliver_code = lambda recipient, kind, code, db: sent.append((recipient.phone, kind, code))
    # Existing customer challenge is unaffected by rep verification.
    access.otp_hash = secret_digest(access.id + ':654321')
    access.otp_expires = datetime.utcnow() + timedelta(minutes=10)
    access.contact_hash = contact_fingerprint(lead)
    db.commit()
    mod.send_code(mod.CodeRequest(channel=channel), access, db, rep_request)
    assert sent[0][:2] == (phone, 'sms')
    assert access.otp_hash == secret_digest(access.id + ':654321')
    result = mod.verify_code(mod.VerifyCode(code=sent[0][2]), access, db, rep_request)
    assert mod.verified(access, request(mod.rep_link_token(access), result['session']), db).id == access.id
    with pytest.raises(HTTPException):
        mod.verified(access, request(link_token(access.id), result['session']), db)
    customer = mod.verify_code(mod.VerifyCode(code='654321'), access, db)
    with pytest.raises(HTTPException):
        mod.verified(access, request(mod.rep_link_token(access), customer['session']), db)
    # Reassignment invalidates rep verification, even if the company phone stays the same.
    lead.assigned_to = None
    db.commit()
    with pytest.raises(HTTPException):
        mod.verified(access, request(mod.rep_link_token(access), result['session']), db)


def test_rep_verification_rejects_customer_channels_and_missing_phones(rep_portal):
    mod, db, lead, access, rep, company = rep_portal
    rep_request = request(mod.rep_link_token(access))
    mod.deliver_code = MagicMock()
    for channel in ['sms', 'email']:
        with pytest.raises(HTTPException):
            mod.send_code(mod.CodeRequest(channel=channel), access, db, rep_request)
    with pytest.raises(HTTPException):
        mod.send_code(mod.CodeRequest(channel='rep_sms'), access, db, request(link_token(access.id)))
    rep.phone = ''
    company.phone = ''
    db.commit()
    assert mod.verify_options(access, db, rep_request)['options'] == []
    with pytest.raises(HTTPException):
        mod.send_code(mod.CodeRequest(channel='company_sms'), access, db, rep_request)
    mod.deliver_code.assert_not_called()


def test_rep_code_and_session_expire_when_contact_changes(rep_portal):
    mod, db, lead, access, rep, company = rep_portal
    rep_request = request(mod.rep_link_token(access))
    sent = []
    mod.deliver_code = lambda recipient, kind, code, db: sent.append(code)
    mod.send_code(mod.CodeRequest(channel='rep_sms'), access, db, rep_request)
    rep.phone = '+12405550333'
    db.commit()
    with pytest.raises(HTTPException):
        mod.verify_code(mod.VerifyCode(code=sent[0]), access, db, rep_request)


def test_rep_http_flow_injects_request_and_reuses_move_page(rep_portal):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    mod, db, lead, access, rep, company = rep_portal
    sent = []
    mod.deliver_code = lambda recipient, kind, code, db: sent.append((recipient.phone, code))
    mod._read_job_route = lambda *args: ('A', [], 'B')
    # Avoid loading pricing for this authentication-only test.
    lead.company_id = None
    company.is_default_company = True
    db.commit()
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_db] = lambda: db
    with TestClient(app) as client:
        headers = {'x-public-link': mod.rep_link_token(access)}
        base = f'/api/public-moves/{access.id}'
        assert client.get(base + '/details', headers=headers).status_code == 401
        assert client.get(base + '/verify-options', headers=headers).json()['audience'] == 'rep'
        assert client.post(base + '/send-code', headers=headers, json={'channel': 'company_sms'}).status_code == 200
        assert sent[0][0] == company.phone
        verified = client.post(base + '/verify', headers=headers, json={'code': sent[0][1]})
        assert verified.status_code == 200, verified.text
        headers['x-public-session'] = verified.json()['session']
        response = client.get(base + '/details', headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['name'] == lead.full_name


def test_new_runs_have_new_conversations_and_all_move_files(portal, processing_api, monkeypatch):
    from spark_history import activate_report
    mod, db, lead, access = portal
    old = {'id': 'conversation-old', 'hostJoinUrl': 'host-old', 'participantJoinUrl': 'participant-old',
           'last_spark_id': 'report-old', 'last_spark_status': 'completed', 'last_spark_share_url': 'report-url',
           'spark_extracted_cuft': 50, 'report_files': [{'id': 'a', 'name': 'first.jpg'}]}
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps(old)))
    for file_id, job_id in [('a', access.job_id), ('b', None), ('deleted', access.job_id)]:
        db.add(models.LeadAttachment(id=file_id, lead_id=lead.id, job_id=job_id, file_name=file_id+'.jpg',
               file_blob=b'image', file_size=5, content_type='image/jpeg',
               report_deleted_at=datetime.utcnow() if file_id == 'deleted' else None))
    db.commit()
    monkeypatch.setenv('PUBLIC_MOVE_SYNC_QUEUE_URL', 'test-queue')
    sync = ModuleType('public_move_sync')
    sync.queue_files = MagicMock()
    monkeypatch.setitem(sys.modules, 'public_move_sync', sync)
    api = processing_api
    api['_connection_config'] = lambda: {'spark_template_id': 'template'}
    api['ensure_lead_conversation'] = MagicMock(return_value={'id': 'conversation-new', 'hostJoinUrl': 'host-new', 'participantJoinUrl': 'participant-new'})
    api['_api_post'] = MagicMock(return_value={'id': 'report-new', 'status': 'queued'})
    result = api['trigger_lead_spark'](lead.id, None, db)
    assert result['status'] == 'queued'
    api['ensure_lead_conversation'].assert_called_once_with(lead, db, fresh=True)
    api['_api_post'].assert_not_called()
    sync.queue_files.assert_called_once_with(access.id, db)
    saved = db.get(models.LeadLiveSwitch, lead.id)
    snapshot = json.loads(saved.details)
    assert snapshot['id'] == 'conversation-new'
    assert {f['id'] for f in snapshot['report_files']} == {'a', 'b'}
    assert 'spark_extracted_cuft' not in snapshot
    # A partial transfer must not start a report.
    rows = db.query(models.PublicMoveUpload).all()
    rows[0].synced_at = datetime.utcnow()
    db.commit()
    api['start_ready_report'](lead.id, db)
    api['_api_post'].assert_not_called()
    rows[1].synced_at = datetime.utcnow()
    db.commit()
    import boto3
    queue = MagicMock()
    monkeypatch.setattr(boto3, 'client', lambda *args, **kwargs: queue)
    api['start_ready_report'](lead.id, db)
    api['_api_post'].assert_not_called()
    assert queue.send_message.call_args.kwargs['DelaySeconds'] == 60
    api['start_ready_report'](lead.id, db)
    assert queue.send_message.call_count == 1
    rows[0].synced_at = datetime.utcnow() - timedelta(seconds=120)
    rows[1].synced_at = datetime.utcnow() - timedelta(seconds=59)
    db.commit()
    api['start_ready_report'](lead.id, db)
    api['_api_post'].assert_not_called()
    rows[1].synced_at = datetime.utcnow() - timedelta(seconds=61)
    db.commit()
    api['start_ready_report'](lead.id, db)
    api['_api_post'].assert_called_once_with('conversations/conversation-new/sparks', {'sparkTemplateId': 'template', 'shareWith': ['anyone']})
    api['start_ready_report'](lead.id, db)
    assert api['_api_post'].call_count == 1
    snapshot = json.loads(saved.details)
    assert snapshot['last_spark_id'] == 'report-new'
    assert len(snapshot['spark_history']) == 2
    activate_report(snapshot, 'report-old')
    assert snapshot['id'] == 'conversation-old'
    assert snapshot['hostJoinUrl'] == 'host-old'
    assert snapshot['participantJoinUrl'] == 'participant-old'
    assert snapshot['report_files'] == [{'id': 'a', 'name': 'first.jpg'}]


def test_customer_file_list_uses_selected_report_snapshot(portal):
    mod, db, lead, access = portal
    snapshot = [{'id': 'old-photo', 'name': 'old.jpg', 'size': 10}]
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'old',
        'last_spark_status': 'completed', 'spark_extracted_id': 'old', 'report_files': snapshot})))
    db.commit()
    mod._read_job_route = lambda *args: ('A', [], 'B')
    assert mod.details(access, db)['files'] == snapshot


def test_file_worker_uses_pinned_conversation_even_if_selection_changes(portal, monkeypatch):
    mod, db, lead, access = portal
    attachment = models.LeadAttachment(id='pinned-photo', lead_id=lead.id, job_id=None,
        file_name='photo.jpg', file_blob=b'image', file_size=5, content_type='image/jpeg')
    db.add(attachment)
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'id': 'different-conversation'})))
    db.flush()
    row = models.PublicMoveUpload(attachment_id=attachment.id, access_id=access.id, request_id='file',
        sync_token='token', sync_status='queued')
    db.add(row)
    db.commit()
    liveswitch = ModuleType('routes.liveswitch')
    liveswitch._api_post = MagicMock(return_value={'results': [{'fileName': 'pinned-photo-photo.jpg',
        'presignedUrl': 'https://bucket.s3.amazonaws.com/upload'}]})
    liveswitch.start_ready_report = MagicMock()
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', liveswitch)
    leads = ModuleType('routes.leads')
    leads._stored_attachment_bytes = lambda attachment: b'image'
    monkeypatch.setitem(sys.modules, 'routes.leads', leads)
    spec = importlib.util.spec_from_file_location('test_sync_worker', BACKEND / 'public_move_sync_handler.py')
    worker = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'database': SimpleNamespace(SessionLocal=None)}):
        spec.loader.exec_module(worker)
    put = MagicMock()
    monkeypatch.setattr(worker.httpx, 'put', put)
    message = {'attachment_id': attachment.id, 'access_id': access.id, 'sync_token': 'token',
               'conversation_id': 'original-conversation'}
    worker.process_file(message, db)
    assert row.synced_at is not None
    assert liveswitch._api_post.call_args.args[0] == 'conversations/original-conversation/upload-urls/images'
    liveswitch.start_ready_report.assert_called_once_with(lead.id, db)
    worker.process_file(message, db)
    assert put.call_count == 1


def test_delete_report_file_excludes_it_but_preserves_history(portal):
    from report_files import move_files
    mod, db, lead, access = portal
    for item_id in ['keep', 'remove']:
        db.add(models.LeadAttachment(id=item_id, lead_id=lead.id, job_id=access.job_id,
            file_name=item_id+'.jpg', file_blob=b'image', file_size=5, content_type='image/jpeg'))
    snapshot = [{'id': item_id, 'name': item_id+'.jpg'} for item_id in ['keep', 'remove']]
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({'last_spark_id': 'old',
        'last_spark_status': 'completed', 'spark_extracted_id': 'old', 'report_files': snapshot})))
    db.commit()
    assert mod.delete_customer_report_file('remove', access, db)['ok']
    assert mod.delete_customer_report_file('remove', access, db)['ok']  # Repeat is harmless.
    assert [f.id for f in move_files(access, db)] == ['keep']
    assert db.get(models.LeadAttachment, 'remove').file_blob == b'image'
    mod._read_job_route = lambda *args: ('A', [], 'B')
    result = mod.details(access, db)
    assert result['files'] == snapshot
    assert result['report_history'][0]['files'] == snapshot
    assert [f['id'] for f in result['editable_files']] == ['keep']
    assert result['files_changed']
    mod.delete_customer_report_file('keep', access, db)
    with pytest.raises(HTTPException) as exc:
        mod.customer_generate_inventory_report(access, db)
    assert exc.value.status_code == 400


def test_delete_file_rejects_another_move(portal):
    mod, db, lead, access = portal
    other_job = models.LeadJob(id='different-job', lead_id=lead.id, job_order=2)
    db.add(other_job)
    db.flush()
    db.add(models.LeadAttachment(id='other-file', lead_id=lead.id, job_id=other_job.id,
        file_name='other.jpg', file_blob=b'image', file_size=5, content_type='image/jpeg'))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        mod.delete_customer_report_file('other-file', access, db)
    assert exc.value.status_code == 404
    assert db.get(models.LeadAttachment, 'other-file').report_deleted_at is None


def test_staff_file_delete_checks_staff_access(portal):
    mod, db, lead, access = portal
    def forbidden(*args):
        raise HTTPException(403, 'Not assigned')
    mod.staff_access = forbidden
    with pytest.raises(HTTPException) as exc:
        mod.delete_staff_report_file(lead.id, 'file', object(), db)
    assert exc.value.status_code == 403


@pytest.mark.parametrize('authenticated', [False, True])
def test_file_delete_requires_verified_customer_session(portal, monkeypatch, authenticated):
    import ast
    import re
    from uuid import uuid4
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    mod, db, lead, access = portal
    access.id = str(uuid4())
    access.token_hash = digest(link_token(access.id))
    token = 'delete-session'
    db.add(models.PublicMoveSession(token_hash=digest(token), access_id=access.id,
        expires_at=datetime.utcnow() + timedelta(hours=1), contact_hash=contact_fingerprint(lead)))
    db.commit()
    remove = MagicMock(return_value={'ok': True})
    monkeypatch.setattr(mod, 'remove_report_file', remove)
    source = ast.parse((BACKEND / 'main.py').read_text(encoding='utf-8'))
    node = next(node for node in source.body if getattr(node, 'name', '') == 'enforce_authentication')
    scope = {'Request': Request, 're': re, 'HTTPException': HTTPException, 'PUBLIC_PATHS': set()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<global-auth>', 'exec'), scope)
    app = FastAPI(dependencies=[Depends(scope['enforce_authentication'])])
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_db] = lambda: db
    with TestClient(app) as client:
        headers = {'x-public-link': link_token(access.id)}
        if authenticated:
            headers['x-public-session'] = token
        response = client.delete(f'/api/public-moves/{access.id}/files/photo', headers=headers)
        assert response.status_code == (200 if authenticated else 401), response.text
    assert remove.call_count == (1 if authenticated else 0)


@pytest.fixture
def manual_catalog(portal):
    mod, db, lead, access = portal
    db.add(models.InventoryRoomType(id='bedroom', name='Bedroom', sort_order=0))
    db.add(models.InventoryCatalogItem(id='chair', name='Chair', cuft=10, weight=70, description=''))
    db.add(models.InventoryCatalogItem(id='table', name='Table', cuft=20, weight=140, description=''))
    db.commit()
    return portal


def test_manual_list_uses_shared_pricing_without_liveswitch(manual_catalog, processing_api, monkeypatch):
    from manual_inventory import ManualInventoryInput, submit_inventory
    from spark_history import report_history
    from uuid import uuid4
    mod, db, lead, access = manual_catalog
    liveswitch = ModuleType('routes.liveswitch')
    liveswitch.apply_spark_results_to_lead = processing_api['apply_spark_results_to_lead']
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', liveswitch)
    pricing = ModuleType('routes.pricing')
    def calculate(lead, job, db):
        job.price = lead.volume * 10
        return float(job.price)
    pricing.calculate_and_save_lead_job_price = MagicMock(side_effect=calculate)
    monkeypatch.setitem(sys.modules, 'routes.pricing', pricing)
    body = ManualInventoryInput(request_id=uuid4(), rooms=[{'room_type_id': 'bedroom', 'name': 'Bedroom 1',
        'items': [{'item_id': 'chair', 'quantity': 2}, {'item_id': 'table', 'quantity': 1}]}])
    result = submit_inventory(body, access, db)
    assert result['ok'] and result['price'] == 400
    assert float(lead.volume) == 40 and float(lead.weight) == 280
    assert float(access.published_price) == 400
    assert db.query(models.LeadSparkInventoryItem).count() == 2
    processing_api['httpx'].get.assert_not_called()
    pricing.calculate_and_save_lead_job_price.assert_called_once()
    saved = db.get(models.LeadLiveSwitch, lead.id)
    first_id = json.loads(saved.details)['last_spark_id']
    assert report_history(json.loads(saved.details))[0]['source'] == 'manual'
    assert report_history(json.loads(saved.details))[0]['inventory'][0]['room'] == 'Bedroom 1'
    # Replaying the same submission does not create another history entry.
    assert submit_inventory(body, access, db)['ok']
    assert len(report_history(json.loads(saved.details))) == 1
    body.request_id = uuid4()
    body.rooms[0].items[0].quantity = 1
    assert submit_inventory(body, access, db)['price'] == 300
    assert len(report_history(json.loads(saved.details))) == 2
    # Historical totals come from the saved list, even if catalog values later change.
    db.get(models.InventoryCatalogItem, 'chair').cuft = 99
    db.commit()
    assert processing_api['select_spark_report'](lead.id, first_id, db)['price'] == 400
    processing_api['httpx'].get.assert_not_called()
    mod._read_job_route = lambda *args: ('A', [], 'B')
    response = mod.details(access, db)
    assert response['spark']['source'] == 'manual'
    assert response['estimate']['price'] == '400.00'


def test_manual_inventory_rejects_unknown_items_and_client_measurements(manual_catalog):
    from manual_inventory import ManualInventoryInput, build_inventory
    from uuid import uuid4
    mod, db, lead, access = manual_catalog
    body = {'request_id': str(uuid4()), 'rooms': [{'room_type_id': 'bedroom', 'name': 'Bedroom',
             'items': [{'item_id': 'chair', 'quantity': 2}]}]}
    assert build_inventory(ManualInventoryInput(**body), db)[2:] == (20, 140)
    body['rooms'][0]['items'][0]['cuft'] = 1
    with pytest.raises(ValueError):
        ManualInventoryInput(**body)
    del body['rooms'][0]['items'][0]['cuft']
    body['rooms'][0]['items'][0]['item_id'] = 'unknown'
    with pytest.raises(HTTPException):
        build_inventory(ManualInventoryInput(**body), db)
    body['rooms'][0]['items'][0]['item_id'] = 'chair'
    body['rooms'][0]['items'][0]['quantity'] = -1
    with pytest.raises(ValueError):
        ManualInventoryInput(**body)


def test_catalog_seed_is_idempotent_and_preserves_volume_variants(portal):
    from inventory_catalog_seed import seed_inventory_catalog
    mod, db, lead, access = portal
    seed_inventory_catalog(db.connection())
    seed_inventory_catalog(db.connection())
    db.commit()
    assert db.query(models.InventoryCatalogItem).count() == 770
    assert db.query(models.InventoryRoomType).count() == 16
    values = db.query(models.InventoryCatalogItem).filter_by(name='Bed Platform').all()
    assert {float(r.cuft) for r in values} == {15, 30}
    assert {float(r.weight) for r in values} == {105, 210}


@pytest.mark.parametrize('authenticated', [False, True])
def test_manual_inventory_endpoints_require_verification(manual_catalog, monkeypatch, authenticated):
    import ast
    import re
    from uuid import uuid4
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    mod, db, lead, access = manual_catalog
    access.id = str(uuid4())
    access.token_hash = digest(link_token(access.id))
    token = 'manual-session'
    db.add(models.PublicMoveSession(token_hash=digest(token), access_id=access.id,
        expires_at=datetime.utcnow() + timedelta(hours=1), contact_hash=contact_fingerprint(lead)))
    db.commit()
    save = MagicMock(return_value={'ok': True, 'price': 400})
    monkeypatch.setattr(mod, 'save_inventory_draft', save)
    source = ast.parse((BACKEND / 'main.py').read_text(encoding='utf-8'))
    node = next(node for node in source.body if getattr(node, 'name', '') == 'enforce_authentication')
    scope = {'Request': Request, 're': re, 'HTTPException': HTTPException, 'PUBLIC_PATHS': set()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<global-auth>', 'exec'), scope)
    app = FastAPI(dependencies=[Depends(scope['enforce_authentication'])])
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_db] = lambda: db
    with TestClient(app) as client:
        headers = {'x-public-link': link_token(access.id)}
        if authenticated:
            headers['x-public-session'] = token
        base = f'/api/public-moves/{access.id}'
        response = client.get(base + '/inventory-catalog', headers=headers)
        assert response.status_code == (200 if authenticated else 401), response.text
        if authenticated:
            assert response.json()['items'][0]['cuft'] == 10
        response = client.post(base + '/manual-inventory', headers=headers, json={'request_id': str(uuid4()),
            'rooms': [{'room_type_id': 'bedroom', 'name': 'Bedroom', 'items': [{'item_id': 'chair', 'quantity': 2}]}]})
        assert response.status_code == (200 if authenticated else 401), response.text
    assert save.call_count == (1 if authenticated else 0)


def test_gallery_preview_is_scoped_and_hides_deleted_files(portal, monkeypatch):
    import boto3
    from unittest.mock import Mock
    mod, db, lead, access = portal
    client = Mock()
    client.generate_presigned_url.return_value = 'https://signed.example/photo'
    monkeypatch.setattr(boto3, 'client', lambda service: client)
    db.add(models.LeadJob(id='gallery-other-job', lead_id=lead.id, job_order=2))
    db.flush()
    for item_id, job, mime in [('photo', access.job_id, 'image/jpeg'), ('other', 'gallery-other-job', 'image/jpeg'), ('document', access.job_id, 'application/pdf')]:
        db.add(models.LeadAttachment(id=item_id, lead_id=lead.id, job_id=job,
            file_name=item_id, file_size=5, file_blob=b'', content_type=mime, external_url='s3://bucket/photos/image.jpg'))
    db.commit()
    assert mod.customer_file_preview('photo', access, db)['url'] == 'https://signed.example/photo'
    client.generate_presigned_url.assert_called_once_with('get_object', Params={
        'Bucket': 'bucket', 'Key': 'photos/image.jpg', 'ResponseContentType': 'image/jpeg',
        'ResponseContentDisposition': 'inline'}, ExpiresIn=3600)
    assert mod.customer_file_preview('document', access, db) == {'url': None}
    with pytest.raises(HTTPException) as exc:
        mod.customer_file_preview('other', access, db)
    assert exc.value.status_code == 404
    mod.delete_customer_report_file('photo', access, db)
    with pytest.raises(HTTPException) as exc:
        mod.customer_file_preview('photo', access, db)
    assert exc.value.status_code == 404


def test_saving_list_does_not_generate_report(manual_catalog):
    from manual_inventory import ManualInventoryInput
    from uuid import uuid4
    mod, db, lead, access = manual_catalog
    body = ManualInventoryInput(request_id=uuid4(), rooms=[{'room_type_id': 'bedroom', 'name': 'Bedroom',
        'items': [{'item_id': 'chair', 'quantity': 2}]}])
    assert mod.submit_customer_inventory(body, access, db)['ok']
    details = json.loads(db.get(models.LeadLiveSwitch, lead.id).details)
    assert details['inventory_draft']['cuft'] == 20
    assert not details.get('last_spark_id')
    assert db.query(models.LeadSparkInventoryItem).count() == 0
    body.rooms = []
    mod.submit_customer_inventory(body, access, db)
    assert json.loads(db.get(models.LeadLiveSwitch, lead.id).details)['inventory_draft']['rows'] == []


def test_combined_report_uses_snapshot_once_on_recalculation(portal, processing_api, monkeypatch):
    mod, db, lead, access = portal
    db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({
        'last_spark_id': 'combined-report', 'last_spark_status': 'completed', 'report_source': 'combined',
        'report_list_cuft': 20, 'report_list_weight': 140,
        'report_list_rows': [{'name': 'Chair', 'room': 'Bedroom', 'amount': 2, 'cuft': 20, 'weight': 140}],
        'inventory_draft': {'cuft': 999}})))
    db.commit()
    processing_api['fetch_and_extract_spark_report'] = MagicMock(return_value=(60, 0, [{'name': 'TV', 'amount': 3, 'cuft': 60}]))
    pricing = ModuleType('routes.pricing')
    def calculate(lead, job, db):
        job.price = lead.volume * 10
        return float(job.price)
    pricing.calculate_and_save_lead_job_price = calculate
    monkeypatch.setitem(sys.modules, 'routes.pricing', pricing)
    for _ in range(2):
        result = processing_api['apply_spark_results_to_lead'](lead.id, 'https://example.com/report', db)
        assert result['ok'], result
        assert float(lead.volume) == 80
        assert result['price'] == 800
        assert db.query(models.LeadSparkInventoryItem).count() == 2


def test_custom_inventory_volume_and_validation(manual_catalog):
    from manual_inventory import ManualInventoryInput, build_inventory
    from uuid import uuid4
    from pydantic import ValidationError
    mod, db, lead, access = manual_catalog
    body = {'request_id': str(uuid4()), 'rooms': [{'room_type_id': 'bedroom', 'name': 'Bedroom', 'items': [],
        'custom_items': [{'id': str(uuid4()), 'name': 'Custom cabinet', 'cuft': 12.5, 'quantity': 2}]}]}
    parsed = ManualInventoryInput.model_validate(body)
    rooms, rows, cuft, weight = build_inventory(parsed, db)
    assert cuft == 25 and weight == 0
    assert rows[0]['name'] == 'Custom cabinet' and rows[0]['custom']
    assert mod.submit_customer_inventory(parsed, access, db)['ok']
    saved = json.loads(db.get(models.LeadLiveSwitch, lead.id).details)['inventory_draft']
    assert saved['cuft'] == 25 and saved['body']['rooms'][0]['custom_items'][0]['name'] == 'Custom cabinet'
    for invalid in [0, -1, 'NaN', 'Infinity', 10001]:
        body['rooms'][0]['custom_items'][0]['cuft'] = invalid
        with pytest.raises(ValidationError):
            ManualInventoryInput.model_validate(body)


def test_send_customer_link_dry_run_and_both_channels(portal, monkeypatch):
    mod, db, lead, access = portal
    lead.phone = '+12025550123'
    lead.email = 'customer@example.test'
    monkeypatch.setattr(mod, 'staff_access', lambda *args: (lead, access))
    sms = MagicMock(return_value={'ok': True})
    ses = MagicMock()
    monkeypatch.setattr(mod, 'send_customer_link', sms)
    monkeypatch.setattr(mod.boto3, 'client', MagicMock(return_value=ses))
    monkeypatch.setattr(mod, 'setting', lambda key: {'PUBLIC_MOVE_LINK_DRY_RUN': 'false', 'PUBLIC_MOVE_EMAIL_FROM': 'sender@example.test', 'PUBLIC_MOVE_ORIGIN': 'https://move.example.test', 'AWS_REGION': 'us-east-1'}.get(key, ''))
    result = mod.send_customer_page_link(lead.id, mod.SendCustomerLinkRequest(dry_run=True), object(), db)
    assert result['dry_run'] and len(result['deliveries']) == 2
    assert mod.public_url(access) in result['message']
    sms.assert_not_called()
    ses.send_email.assert_not_called()
    result = mod.send_customer_page_link(lead.id, mod.SendCustomerLinkRequest(dry_run=False), object(), db)
    assert result['ok'] and all(row['status'] == 'sent' for row in result['deliveries'])
    sms.assert_called_once()
    ses.send_email.assert_called_once()
    sms.side_effect = HTTPException(502, 'SMS failed')
    result = mod.send_customer_page_link(lead.id, mod.SendCustomerLinkRequest(dry_run=False), object(), db)
    assert not result['ok']
    assert [row['status'] for row in result['deliveries']] == ['failed', 'sent']


def test_environment_dry_run_prevents_customer_link_delivery(portal, monkeypatch):
    mod, db, lead, access = portal
    monkeypatch.setattr(mod, 'staff_access', lambda *args: (lead, access))
    monkeypatch.setattr(mod, 'setting', lambda key: 'https://move.example.test' if key == 'PUBLIC_MOVE_ORIGIN' else 'true')
    sms = MagicMock()
    monkeypatch.setattr(mod, 'send_customer_link', sms)
    provider = MagicMock()
    monkeypatch.setattr(mod.boto3, 'client', provider)
    result = mod.send_customer_page_link(lead.id, mod.SendCustomerLinkRequest(dry_run=False), object(), db)
    assert result['dry_run']
    sms.assert_not_called()
    provider.assert_not_called()


def test_import_chat_files_scopes_company_page(portal, monkeypatch):
    mod, db, lead, access = portal
    lead.facebook_user_id = 'client'
    company = models.Company(name='Import company', facebook_page_id='page')
    db.add(company); db.flush()
    lead.company_id = company.id
    db.commit()
    monkeypatch.setattr(mod, 'staff_access', lambda *args: (lead, access))
    source = ModuleType('db')
    source.conversations_table = MagicMock()
    monkeypatch.setitem(sys.modules, 'db', source)
    import meta_attachment_archiver
    archive = MagicMock(return_value=1)
    monkeypatch.setattr(meta_attachment_archiver, 'archive_meta_attachments', archive)
    source.conversations_table.query.return_value = {'Items': [{'page_id': 'other', 'platform': 'instagram', 'message_id': 'm', 'attachments': [{'type': 'image'}]}]}
    mod.import_chat_files(lead.id, mod.ImportChatFilesRequest(), object(), db)
    archive.assert_not_called()
    source.conversations_table.query.return_value = {'Items': [{'page_id': 'page', 'platform': 'instagram', 'message_id': 'm', 'attachments': [{'type': 'image'}]}]}
    result = mod.import_chat_files(lead.id, mod.ImportChatFilesRequest(), object(), db)
    assert result['imported'] == 1
    archive.assert_called_once()


@pytest.fixture
def traced_intake(portal, monkeypatch):
    mod, db, lead, access = portal
    monkeypatch.setenv('PUBLIC_MOVE_API_KEY', 'test-intake-key')
    monkeypatch.setenv('PUBLIC_MOVE_ORIGIN', 'https://example.com')
    execute = db.execute
    def without_postgres_lock(statement, *args, **kwargs):
        if 'pg_advisory_xact_lock' in str(statement): return None
        return execute(statement, *args, **kwargs)
    monkeypatch.setattr(db, 'execute', without_postgres_lock)
    body = mod.Intake(first_name='Test', last_name='Customer', source='Website',
        move_date='2026-10-01', pickup='A', delivery='B', phone='2405707987')
    return mod, db, body


def test_intake_trace_success_and_replay(traced_intake):
    mod, db, body = traced_intake
    result = mod.intake(body, request(), 'test-intake-key', 'test-request-key', db)
    assert result['status'] == 'succeeded'
    actions = {a['action']: a for a in result['actions']}
    assert actions['commit']['response'] == {'committed': True}
    assert actions['create_lead']['response']['lead_id'] == result['lead_id']
    repeated = mod.intake(body, request(), 'test-intake-key', 'test-request-key', db)
    assert repeated['reused'] is True
    assert repeated['lead_id'] == result['lead_id']
    assert next(a for a in repeated['actions'] if a['action'] == 'create_lead')['status'] == 'not_attempted'


def test_intake_trace_rollback(traced_intake, monkeypatch):
    mod, db, body = traced_intake
    before = db.query(models.Lead).count()
    def fail(*args): raise HTTPException(503, 'Route storage unavailable')
    monkeypatch.setattr(mod, '_persist_job_route', fail)
    response = mod.intake(body, request(), 'test-intake-key', 'test-request-key', db)
    assert response.status_code == 503
    result = json.loads(response.body)
    actions = {a['action']: a for a in result['actions']}
    assert actions['create_lead']['status'] == 'rolled_back'
    assert actions['save_job_route']['error']['message'] == 'Route storage unavailable'
    assert actions['commit']['status'] == 'not_attempted'
    assert db.query(models.Lead).count() == before


def test_intake_trace_post_commit_error_keeps_ids(traced_intake, monkeypatch):
    mod, db, body = traced_intake
    monkeypatch.setenv('PUBLIC_MOVE_ORIGIN', '')
    response = mod.intake(body, request(), 'test-intake-key', 'test-request-key', db)
    result = json.loads(response.body)
    assert result['status'] == 'partial'
    assert db.get(models.Lead, result['lead_id']) is not None
    assert next(a for a in result['actions'] if a['action'] == 'commit')['status'] == 'succeeded'


def test_intake_trace_auth_failure(traced_intake):
    mod, db, body = traced_intake
    response = mod.intake(body, request(), 'wrong', 'test-request-key', db)
    assert response.status_code == 401
    result = json.loads(response.body)
    assert result['actions'][0]['error']['message'] == 'Not authorized'
    assert next(a for a in result['actions'] if a['action'] == 'create_lead')['status'] == 'not_attempted'



def test_intake_sends_link_once_after_commit(traced_intake, monkeypatch):
    mod, db, body = traced_intake
    monkeypatch.setenv('PUBLIC_MOVE_LINK_DRY_RUN', 'false')
    sent = []
    def deliver(lead, access, session):
        assert session.get(models.PublicMoveAccess, access.id) is not None
        sent.append(lead.id)
        return {'ok': True}
    monkeypatch.setattr(mod, 'deliver_customer_link_sms', deliver)
    result = mod.intake(body, request(), 'test-intake-key', 'sms-request-key', db)
    assert next(a for a in result['actions'] if a['action'] == 'send_customer_sms')['status'] == 'succeeded'
    mod.intake(body, request(), 'test-intake-key', 'sms-request-key', db)
    assert sent == [result['lead_id']]


def test_intake_sms_failure_keeps_lead_and_link(traced_intake, monkeypatch):
    mod, db, body = traced_intake
    monkeypatch.setenv('PUBLIC_MOVE_LINK_DRY_RUN', 'false')
    def fail(*args): raise HTTPException(502, 'SMS provider failed')
    monkeypatch.setattr(mod, 'deliver_customer_link_sms', fail)
    response = mod.intake(body, request(), 'test-intake-key', 'sms-request-key', db)
    result = json.loads(response.body)
    assert result['status'] == 'partial'
    assert result['url'].startswith('https://example.com/move/')
    assert db.get(models.Lead, result['lead_id']) is not None
    action = next(a for a in result['actions'] if a['action'] == 'send_customer_sms')
    assert action['status'] == 'failed'
    assert action['error']['message'] == 'SMS provider failed'


def test_intake_sms_respects_dry_run(traced_intake, monkeypatch):
    mod, db, body = traced_intake
    monkeypatch.setenv('PUBLIC_MOVE_LINK_DRY_RUN', 'true')
    sender = MagicMock()
    monkeypatch.setattr(mod, 'deliver_customer_link_sms', sender)
    result = mod.intake(body, request(), 'test-intake-key', 'sms-request-key', db)
    sender.assert_not_called()
    assert next(a for a in result['actions'] if a['action'] == 'send_customer_sms')['response']['dry_run'] is True


@pytest.mark.parametrize('accepted', [True, False])
def test_customer_link_sms_notice_only_after_success(portal, monkeypatch, accepted):
    mod, db, lead, access = portal
    monkeypatch.setenv('PUBLIC_MOVE_ORIGIN', 'https://example.com')
    company = models.Company(id='sms-company', name='Test Movers', aircall_number_id='123')
    db.add(company)
    lead.company = company
    db.commit()
    monkeypatch.setattr(mod, 'send_sms', lambda **kwargs: {'ok': accepted})
    assert mod.customer_link_sms_notice(access) is None
    if accepted:
        mod.deliver_customer_link_sms(lead, access, db)
        db.expire_all()
        notice = mod.customer_link_sms_notice(db.get(models.PublicMoveAccess, access.id))
        assert notice['phone_last4'] == '7987'
        assert notice['sent_at']
        assert mod.verify_options(access, db)['link_sms'] == notice
    else:
        with pytest.raises(HTTPException): mod.deliver_customer_link_sms(lead, access, db)
        db.expire_all()
        assert mod.customer_link_sms_notice(access) is None



def test_cognito_email_code_is_single_use(portal, monkeypatch):
    import customer_email_auth
    mod, db, lead, access = portal
    sent = []
    monkeypatch.setattr(customer_email_auth, 'send_email_code', lambda *args: sent.append(args))
    result = mod.send_code(mod.CodeRequest(channel='email'), access, db)
    email, code, access_id = sent[0]
    assert email == lead.email and access_id == access.id
    assert code not in json.dumps(result)
    assert code not in access.otp_hash
    result = mod.verify_code(mod.VerifyCode(code=code), access, db)
    assert db.get(models.PublicMoveSession, digest(result['session']))
    with pytest.raises(HTTPException): mod.verify_code(mod.VerifyCode(code=code), access, db)


def test_cognito_send_failure_invalidates_code(portal, monkeypatch):
    import customer_email_auth
    mod, db, lead, access = portal
    def fail(*args): raise HTTPException(502, 'Could not send email')
    monkeypatch.setattr(customer_email_auth, 'send_email_code', fail)
    with pytest.raises(HTTPException): mod.send_code(mod.CodeRequest(channel='email'), access, db)
    assert access.otp_hash is None
    assert db.query(models.PublicMoveSession).count() == 0

def test_item_answers_validate_report_choice_and_acknowledgment(portal, monkeypatch):
    mod, db, lead, access = portal
    from inventory_questions import questions
    company=models.Company(id='questions-company',name='Questions Co',customer_questions=json.dumps([{
        'id':'plant','title':'Plant','enabled':True,'question':'Is it live?','item_ids':[],'words':['plant'],'photo':False,
        'answers':[{'id':'yes','label':'Yes','action':'exclude','notice':'Not accepted','acknowledge':True},
                   {'id':'no','label':'No','action':'none','notice':'','acknowledge':False}]}]))
    db.add(company); lead.company=company
    state={'last_spark_id':'report','last_spark_status':'completed','spark_inventory_snapshot':[{'name':'Plant','cuft':10,'amount':1}]}
    conversation=models.LeadLiveSwitch(lead_id=lead.id,details=json.dumps(state)); db.add(conversation); db.commit()
    question=questions(company,state,db)[0]
    apply=MagicMock(return_value={'ok':True})
    monkeypatch.setitem(sys.modules,'routes.liveswitch',SimpleNamespace(apply_spark_results_to_lead=apply))
    monkeypatch.setattr(mod,'details',lambda access,db: {'updated':True})
    body=dict(report_id='report',question_id=question['id'],answer_id='yes')
    for changes,status in [({'report_id':'old'},409),({'question_id':'bad'},409),({'answer_id':'bad'},400),({},400)]:
        with pytest.raises(HTTPException) as exc:
            mod.save_item_answer(mod.ItemAnswerInput(**{**body,**changes}),access,db)
        assert exc.value.status_code==status
    assert not apply.called
    assert mod.save_item_answer(mod.ItemAnswerInput(**body,acknowledged=True),access,db)=={'updated':True}
    stored=json.loads(conversation.details)['report_question_answers'][question['id']]
    assert stored['action']=='exclude' and stored['acknowledged']
    assert stored['name']=='Plant'
    assert apply.call_args.kwargs=={'expected_report_id':'report','use_snapshot':True}
    # Autosave retains an unacknowledged choice without applying its action.
    mod.save_item_answer(mod.ItemAnswerInput(**body, acknowledged=False, pending=True), access, db)
    stored=json.loads(conversation.details)['report_question_answers'][question['id']]
    assert stored['pending'] and stored['action']=='pending' and not stored['acknowledged']
    mod.save_item_answer(mod.ItemAnswerInput(**body, acknowledged=True, pending=False), access, db)
    stored=json.loads(conversation.details)['report_question_answers'][question['id']]
    assert not stored['pending'] and stored['action']=='exclude'

def test_question_manager_company_scope_and_revision(portal, monkeypatch):
    mod, db, lead, access = portal
    company=models.Company(id='rule-company', name='Rules')
    other=models.Company(id='other-company', name='Other')
    db.add_all([company,other]); db.commit()
    mocks={name:MagicMock() for name in ['auth','database','routes.leads']}
    mocks['auth'].require_admin=lambda:None
    mocks['database'].get_db=lambda:None
    mocks['routes.leads']._get_user_company_ids=lambda user,db:[company.id]
    spec=importlib.util.spec_from_file_location('test_question_routes',BACKEND/'routes/inventory_questions.py')
    api=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,mocks): spec.loader.exec_module(api)
    user=SimpleNamespace(id='admin',role='admin')
    with pytest.raises(HTTPException) as exc: api.get_rules(other.id,user,db)
    assert exc.value.status_code==403
    initial=api.get_rules(company.id,user,db)
    rule={'id':'rule','title':'Plants','question':'Live plant?','words':['plant'],'answers':[
        {'id':'yes','label':'Yes','action':'notice','notice':'Please contact us'}, {'id':'no','label':'No'}]}
    body=api.RulesInput(revision=initial['revision'],rules=[rule])
    result=api.save_rules(company.id,body,user,db)
    assert result['rules'][0]['question']=='Live plant?'
    with pytest.raises(HTTPException) as exc: api.save_rules(company.id,body,user,db)
    assert exc.value.status_code==409
    rule['item_ids']=['missing']
    with pytest.raises(HTTPException) as exc:
        api.save_rules(company.id,api.RulesInput(revision=result['revision'],rules=[rule]),user,db)
    assert exc.value.status_code==400
    assert other.customer_questions is None

@pytest.mark.parametrize('text', ['', '   '])
def test_customer_route_edits_require_selected_place(portal, text):
    mod, db, lead, access = portal
    with pytest.raises(HTTPException) as exc:
        mod.selected_customer_address(text, 'Old address', None, 'Pickup', access.id)
    assert exc.value.status_code == 400


def test_customer_route_city_and_state_selection(portal):
    mod, db, lead, access = portal
    place=mod.CustomerAddressSelection(place_id='google-place-id',formatted_address='Miami, FL, USA',city='Miami',state='FL',country='US')
    import jwt
    place.proof=jwt.encode({'sub':access.id,'aud':'customer-address','exp':int(__import__('time').time())+3600,'address':place.model_dump(exclude={'proof'})},os.environ['JWT_SECRET'],algorithm='HS256')
    assert mod.selected_customer_address('Miami, FL, USA','Old address',place,'Pickup',access.id)=='Miami, FL, USA'
    with pytest.raises(HTTPException):
        mod.selected_customer_address('Different text','Old address',place,'Pickup',access.id)
    assert mod.selected_customer_address('Old address','Old address',None,'Pickup',access.id)=='Old address'
    assert mod.selected_customer_address(None,'Old address',None,'Delivery',access.id)=='Old address'
    for field in ['city','state','place_id']:
        with pytest.raises(ValueError):
            mod.CustomerAddressSelection(**{**place.model_dump(),field:' '})


def test_manual_address_saves_without_google(portal):
    mod, db, lead, access = portal
    place = mod.CustomerAddressSelection(place_id='manual', formatted_address='123 Main St, Miami, FL',
        city='Miami', state='FL', country='US')
    assert mod.selected_customer_address(place.formatted_address, 'Old', place, 'Pickup', access.id) == place.formatted_address
    place.state = 'XX'
    with pytest.raises(HTTPException):
        mod.selected_customer_address(place.formatted_address, 'Old', place, 'Pickup', access.id)


def test_invalid_address_does_not_mutate_customer_details(portal, monkeypatch):
    mod, db, lead, access = portal
    monkeypatch.setattr(mod,'_read_job_route',lambda db,job:('Old pickup',[], 'Old delivery'))
    with pytest.raises(HTTPException):
        mod.update_customer_details(mod.CustomerDetailsPatch(name='Changed',pickup=' '),access,db)
    assert lead.full_name == 'Jane Smith'


def test_selected_customer_route_preserves_stops(portal, monkeypatch):
    mod, db, lead, access = portal
    monkeypatch.setattr(mod,'_read_job_route',lambda db,job:('Old pickup',['Storage'], 'Old delivery'))
    persist=MagicMock(); monkeypatch.setattr(mod,'_persist_job_route',persist)
    monkeypatch.setattr(mod,'details',lambda access,db:{'saved':True})
    body=mod.CustomerDetailsPatch(pickup='Miami, FL, USA',pickup_place=dict(place_id='google-place-id',formatted_address='Miami, FL, USA',city='Miami',state='FL',country='US'))
    import jwt
    body.pickup_place.proof=jwt.encode({'sub':access.id,'aud':'customer-address','exp':int(__import__('time').time())+3600,'address':body.pickup_place.model_dump(exclude={'proof'})},os.environ['JWT_SECRET'],algorithm='HS256')
    assert mod.update_customer_details(body,access,db)=={'saved':True}
    persist.assert_called_once_with(db,access.job_id,'Miami, FL, USA',['Storage'],'Old delivery')

@pytest.mark.parametrize('suffix,payload,expected', [
    ('item-answer', {'report_id':'missing','question_id':'q','answer_id':'yes'}, 409),
    ('question-images', {'names':['Plant']}, 200),
    ('estimate.pdf', None, 200),
    ('realtime-token', {}, 200),
    ('address-search', {'text':'Miami','session_token':'1234567890abcdef'}, 200),
    ('address-resolve', {'place_id':'place1','session_token':'1234567890abcdef'}, 200),
])
def test_new_customer_routes_pass_global_guard_with_scoped_session(portal, monkeypatch, suffix, payload, expected):
    import ast
    import re
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    mod, db, lead, access = portal
    # Exercise the actual global guard, without initializing AWS on app import.
    if suffix == 'estimate.pdf':
        monkeypatch.setattr(mod, '_move_details', lambda *args, **kwargs: {
            'name': lead.full_name, 'estimate': {'price': '100', 'cuft': '5'},
            'spark': {'status': 'completed'}})
        db.add(models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps({
            'spark_inventory_snapshot': [{'name': 'Chair', 'amount': 1, 'cuft': 5}]})))
        db.commit()
    tree=ast.parse((BACKEND/'main.py').read_text(encoding='utf-8'))
    guard=next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='enforce_authentication')
    scope={'Request':Request,'HTTPException':HTTPException,'re':re,'PUBLIC_PATHS':set()}
    exec(compile(ast.Module(body=[guard],type_ignores=[]),'main-auth-guard','exec'),scope)
    access.id='11111111-1111-1111-1111-111111111111'
    access.token_hash=digest(link_token(access.id))
    db.add(models.PublicMoveSession(token_hash=digest('valid-session'),access_id=access.id,expires_at=datetime.utcnow()+timedelta(hours=1),contact_hash=contact_fingerprint(lead)))
    db.commit()
    # The endpoint imports this helper after auth. No real report processing is needed here.
    monkeypatch.setitem(sys.modules,'routes.liveswitch',SimpleNamespace(apply_spark_results_to_lead=MagicMock()))
    import customer_addresses
    monkeypatch.setattr(customer_addresses,'suggestions',lambda *a:[])
    monkeypatch.setattr(customer_addresses,'resolve_address',lambda *a:{'city':'Miami'})
    app=FastAPI(dependencies=[Depends(scope['enforce_authentication'])])
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_db]=lambda:db
    @app.post('/api/public-moves/{access_id}/not-an-approved-route')
    def unrelated(): return {'unexpected': True}
    with TestClient(app) as client:
        path=f'/api/public-moves/{access.id}/{suffix}'
        headers={'x-public-link':link_token(access.id),'x-public-session':'valid-session'}
        send = (lambda **kwargs: client.get(path, **kwargs)) if suffix == 'estimate.pdf' else (lambda **kwargs: client.post(path, json=payload, **kwargs))
        response=send(headers=headers)
        assert response.status_code==expected, response.text
        if suffix == 'estimate.pdf':
            assert response.content.startswith(b'%PDF-')
            assert response.headers['content-type'] == 'application/pdf'
        if suffix == 'realtime-token':
            import jwt
            claims = jwt.decode(response.json()['token'], os.environ['JWT_SECRET'], algorithms=['HS256'], issuer='moving-crm')
            assert claims['sub'] == access.id
            assert claims['lead_id'] == lead.id
            assert claims['role'] == claims['purpose'] == 'customer_updates'
            assert claims['exp'] <= (datetime.utcnow()+timedelta(hours=1)).timestamp()
        # A link alone must never bypass customer verification.
        response=send(headers={'x-public-link':link_token(access.id)})
        assert response.status_code==401
        assert 'verify your phone or email' in response.json()['detail']
        assert send().status_code==404
        assert client.post(f'/api/public-moves/{access.id}/not-an-approved-route',json={}).status_code==401



def test_plain_address_saves_without_selection_or_google(portal):
    mod, db, lead, access = portal
    assert mod.selected_customer_address('  1182 Main St  ', 'Old', None, 'Pickup', access.id) == '1182 Main St'


@pytest.mark.parametrize("floor,volume,expected", [(286, 24, 286), (286, 286, 286), (350, 24, 350), (286, 400, 400)])
def test_customer_package_uses_stored_transport_volume_floor(portal, packing_pricing, floor, volume, expected):
    _, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    job.delivery_zip = 'New York, NY'
    lead.volume = volume
    service = SimpleNamespace(comments='__ld_packing__:' + json.dumps({
        'full': '2', 'partial': '1', 'unpacking': '.50', 'items': []}))
    plan = SimpleNamespace(services=[service], rates=[
        SimpleNamespace(destination='NY', cubic_feet_min=floor),
        SimpleNamespace(destination='FL', cubic_feet_min=900)])
    package = packing_pricing.customer_packing_package(lead, job, db, plan, 'Long Distance')
    assert package['cubic_feet'] == expected
    assert package['inventory_cubic_feet'] == volume
    assert package['minimum_cubic_feet'] == floor
    assert {kind: value['total'] for kind, value in package['rates'].items()} == {
        'full': expected * 2, 'partial': expected, 'unpacking': expected * .5}
    lines = packing_pricing.customer_package_lines(package, {'mode': 'partial', 'unpacking': False})
    assert lines[0]['amount'] == expected
    assert lines[0]['description'].startswith(f'{expected} cu ft')
    assert lead.volume == volume


def test_item_answer_skips_repricing_when_shipping_is_unchanged(portal, monkeypatch):
    mod, db, lead, access = portal
    from inventory_questions import questions
    company = models.Company(id='fast-answers', name='Fast Answers', customer_questions=json.dumps([{
        'id': 'plant', 'title': 'Plant', 'enabled': True, 'question': 'Is it live?', 'words': ['plant'],
        'answers': [{'id': 'yes', 'label': 'Yes', 'action': 'exclude', 'notice': 'Not accepted', 'acknowledge': True},
                    {'id': 'no', 'label': 'No', 'action': 'none', 'notice': '', 'acknowledge': False}]}]))
    db.add(company)
    lead.company = company
    state = {'last_spark_id': 'report', 'last_spark_status': 'completed', 'spark_extracted_cuft': 10,
             'spark_extracted_weight': 5, 'spark_inventory_snapshot': [{'name': 'Plant', 'cuft': 10, 'weight': 5, 'amount': 1}]}
    conversation = models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps(state))
    db.add(conversation)
    db.commit()
    question = questions(company, state, db)[0]
    apply = MagicMock(return_value={'ok': True})
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', SimpleNamespace(apply_spark_results_to_lead=apply))
    monkeypatch.setitem(sys.modules, 'realtime', SimpleNamespace(publish_customer_update=MagicMock()))
    monkeypatch.setattr(mod, 'details', lambda *args: {'updated': True})
    body = dict(report_id='report', question_id=question['id'])
    for answer in [dict(answer_id='no'), dict(answer_id='yes', pending=True)]:
        assert mod.save_item_answer(mod.ItemAnswerInput(**body, **answer), access, db) == {'updated': True}
        assert not apply.called
    mod.save_item_answer(mod.ItemAnswerInput(**body, answer_id='yes', acknowledged=True), access, db)
    apply.assert_called_once()


def test_all_items_answer_requires_selection_and_acknowledgment(portal, monkeypatch):
    mod, db, lead, access = portal
    from inventory_questions import questions
    company = models.Company(id='general-terms', name='General Terms', customer_questions=json.dumps([{
        'id': 'gas', 'title': 'Gas items', 'enabled': True, 'all_items': True,
        'question': 'Any gas-powered items?', 'item_ids': [], 'words': [],
        'answers': [{'id': 'yes', 'label': 'Yes', 'action': 'prepare', 'notice': 'Empty the tank.', 'acknowledge': True},
                    {'id': 'no', 'label': 'No', 'action': 'none', 'notice': '', 'acknowledge': False}]}]))
    db.add(company)
    lead.company = company
    state = {'last_spark_id': 'report', 'last_spark_status': 'completed', 'spark_extracted_cuft': 20,
             'spark_extracted_weight': 100, 'spark_inventory_snapshot': [
                 {'name': 'Mower', 'room': 'Garage', 'cuft': 20, 'weight': 100, 'amount': 2}]}
    conversation = models.LeadLiveSwitch(lead_id=lead.id, details=json.dumps(state))
    db.add(conversation)
    db.commit()
    question, = questions(company, state, db)
    apply = MagicMock(return_value={'ok': True})
    monkeypatch.setitem(sys.modules, 'routes.liveswitch', SimpleNamespace(apply_spark_results_to_lead=apply))
    monkeypatch.setitem(sys.modules, 'realtime', SimpleNamespace(publish_customer_update=MagicMock()))
    monkeypatch.setattr(mod, 'details', lambda *args: {'updated': True})
    def save(**values):
        return mod.save_item_answer(mod.ItemAnswerInput(report_id='report', question_id=question['id'], **values), access, db)
    for values in [dict(answer_id='yes', acknowledged=True),
                   dict(answer_id='yes', selected_items=['9:0'], acknowledged=True),
                   dict(answer_id='yes', selected_items=['0:1'])]:
        with pytest.raises(HTTPException) as error:
            save(**values)
        assert error.value.status_code == 400
    save(answer_id='yes', selected_items=['0:1'], pending=True)
    assert json.loads(conversation.details)['report_question_answers'][question['id']]['pending']
    save(answer_id='yes', selected_items=['0:1'], acknowledged=True)
    saved = json.loads(conversation.details)['report_question_answers'][question['id']]
    assert saved['selected_items'] == ['0:1'] and saved['acknowledged'] and not saved['pending']
    assert saved['selected_item_labels'] == ['Mower (2 of 2) - Garage']
    save(answer_id='no')
    assert json.loads(conversation.details)['report_question_answers'][question['id']]['selected_items'] == []
    apply.assert_not_called()


def test_pricing_autosave_changes_only_selected_charge(portal, packing_pricing, monkeypatch):
    from decimal import Decimal
    mod, db, lead, access = portal
    job = db.get(models.LeadJob, access.job_id)
    job.price = access.published_price = Decimal('1000')
    package = {'cubic_feet': 286, 'rates': {'full': {'rate': 2, 'total': 572}, 'partial': {'rate': 1, 'total': 286},
               'unpacking': {'rate': .5, 'total': 143}}, 'items': [{'id': 'mirror:1', 'label': 'Mirror', 'price': 30}]}
    options = [{'id': 'piano:1', 'name': 'Piano', 'label': 'Piano', 'services': [{'kind': 'packing', 'price': 80}, {'kind': 'crating', 'price': 100}]}]
    monkeypatch.setattr(packing_pricing, 'customer_packing_options', lambda *args: options)
    monkeypatch.setattr(packing_pricing, 'customer_packing_package', lambda *args: package)
    monkeypatch.setitem(sys.modules, 'routes.leads', SimpleNamespace(_refresh_lead_estimated_total=lambda *args: None))
    monkeypatch.setattr(mod, 'details', lambda *args: {})
    db.add(models.LeadJobCharge(id='transport', job_id=job.id, name='Transportation', subtotal=1000, total_cost=1000))
    db.commit()
    def save(**change):
        mod.save_customer_packing(mod.CustomerPackingPatch(change=change), access, db)
    save(kind='bulky', item_id='piano:1', service='packing')
    save(kind='mode', mode='full')
    assert job.price == 1652
    full_id = packing_pricing.customer_packing_charge_id(job.id, 'package:full')
    full = db.get(models.LeadJobCharge, full_id)
    full.description = 'unchanged full packing line'
    db.commit()
    save(kind='unpacking', enabled=True)
    assert job.price == 1795
    assert db.get(models.LeadJobCharge, full_id).description == 'unchanged full packing line'
    assert json.loads(job.customer_packing) == {'piano:1': 'packing'}
    save(kind='unpacking', enabled=True)
    assert job.price == 1795
    save(kind='mode', mode='none')
    save(kind='box', item_id='mirror:1', enabled=True)
    assert job.price == 1253
    save(kind='mode', mode='partial')
    assert job.price == 1509
    assert json.loads(job.customer_packing_package)['item_ids'] == []
    save(kind='bulky', item_id='piano:1', service=None)
    assert job.price == access.published_price == 1429
    assert db.get(models.LeadJobCharge, 'transport').total_cost == 1000


@pytest.mark.parametrize('sms_fails', [False, True])
def test_intake_also_emails_link_once(traced_intake, monkeypatch, sms_fails):
    mod, db, body = traced_intake
    body = body.model_copy(update={'email': 'customer@example.com'})
    monkeypatch.setenv('PUBLIC_MOVE_LINK_DRY_RUN', 'false')
    sms = MagicMock(return_value={'ok': True})
    if sms_fails: sms.side_effect = HTTPException(502, 'SMS provider failed')
    email = MagicMock(return_value={'ok': True})
    monkeypatch.setattr(mod, 'deliver_customer_link_sms', sms)
    monkeypatch.setattr(mod, 'deliver_customer_link_email', email)
    result = mod.intake(body, request(), 'test-intake-key', 'email-create', db)
    result = json.loads(result.body) if sms_fails else result
    assert next(a for a in result['actions'] if a['action'] == 'send_customer_email')['status'] == 'succeeded'
    assert email.call_args.args[0].email == body.email
    assert email.call_args.args[1].lead_id == result['lead_id']
    mod.intake(body, request(), 'test-intake-key', 'email-create', db)
    assert sms.call_count == email.call_count == 1


def test_link_email_uses_configured_sender_and_same_customer_url(portal, monkeypatch):
    mod, db, lead, access = portal
    monkeypatch.setenv('PUBLIC_MOVE_EMAIL_FROM', 'moves@example.com')
    monkeypatch.setenv('PUBLIC_MOVE_ORIGIN', 'https://example.com')
    client = MagicMock()
    monkeypatch.setattr(mod.boto3, 'client', lambda *args, **kwargs: client)
    assert mod.deliver_customer_link_email(lead, access, db) == {'ok': True}
    payload = client.send_email.call_args.kwargs
    assert payload['Source'] == 'moves@example.com'
    assert payload['Destination']['ToAddresses'] == [lead.email]
    assert mod.public_url(access) in payload['Message']['Body']['Text']['Data']
    lead.email = None
    client.reset_mock()
    assert mod.deliver_customer_link_email(lead, access, db)['skipped']
    client.send_email.assert_not_called()


def test_intake_email_dry_run(traced_intake, monkeypatch):
    mod, db, body = traced_intake
    body = body.model_copy(update={'email': 'customer@example.com'})
    monkeypatch.setenv('PUBLIC_MOVE_LINK_DRY_RUN', 'true')
    email = MagicMock()
    monkeypatch.setattr(mod, 'deliver_customer_link_email', email)
    result = mod.intake(body, request(), 'test-intake-key', 'email-dry-run', db)
    email.assert_not_called()
    assert next(a for a in result['actions'] if a['action'] == 'send_customer_email')['response']['dry_run']
