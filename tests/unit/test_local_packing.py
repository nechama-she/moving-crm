"""Local jobs get the customer page's packing step: full packing by the hour (priced with the move), items charged for
their materials only, and no box section."""
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import AppSetting, Base, Lead, LeadJob, PricingPacking, PricingPlan
    from local_pricing import LocalSettings
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(PricingPlan(id='plan', company_name='Movers', name='Local', source_key='plan'))
        session.flush()
        session.add(PricingPacking(plan_id='plan', full=Decimal('2'), partial=Decimal('1')))
        session.add(AppSetting(key='local_pricing:plan', value=LocalSettings(full_pack_hourly=Decimal('65')).model_dump_json()))
        session.add(Lead(id='lead', full_name='Customer', volume=1500))
        session.flush()
        session.add(LeadJob(id='job', lead_id='lead', job_order=1))
        session.commit()
        yield session
    engine.dispose()


def package(db, move_type='Local'):
    from models import Lead, LeadJob, PricingPlan
    from routes.pricing import customer_packing_package
    return customer_packing_package(db.get(Lead, 'lead'), db.get(LeadJob, 'job'), db, db.get(PricingPlan, 'plan'), move_type)


def set_full_pack_hourly(db, rate):
    from models import AppSetting
    from local_pricing import LocalSettings
    db.get(AppSetting, 'local_pricing:plan').value = LocalSettings(full_pack_hourly=Decimal(rate)).model_dump_json()
    db.commit()


def test_local_full_packing_is_by_the_hour_with_no_partial_and_no_boxes(db):
    result = package(db)
    assert result['local'] is True
    # 1,500 cu ft: 2 hours for the first 1,000, 1 more for the rest.
    assert result['rates'] == {'full': {'rate': 65.0, 'per': 'hour', 'hours': 3.0}}
    assert result['box_items'] == []


def test_no_full_packing_without_a_full_pack_rate(db):
    set_full_pack_hourly(db, '0')
    assert package(db)['rates'] == {}


def test_a_local_sheet_without_packing_materials_still_offers_full_packing(db):
    from models import PricingPacking
    db.delete(db.get(PricingPacking, 'plan'))
    db.commit()
    assert package(db)['rates'] == {'full': {'rate': 65.0, 'per': 'hour', 'hours': 3.0}}
    set_full_pack_hourly(db, '0')
    assert package(db) is None  # Neither materials nor a full packing rate: no packing step.


def test_long_distance_keeps_its_rates_per_cubic_foot(db):
    result = package(db, 'Long Distance')
    assert result['local'] is False and set(result['rates']) == {'full', 'partial'}
    assert result['rates']['full']['total'] == 3000


def test_a_local_packed_item_is_charged_for_its_materials_only(db, monkeypatch):
    import item_materials
    import material_calculation
    monkeypatch.setattr(item_materials, 'customer_item_materials', lambda plan, inventory, db: ([
        {'id': 'tv', 'label': 'TV', 'requirement': 'required', 'material_name': 'TV box', 'quantity': 1, 'available': True,
         'price': 50.0, 'labor_price': 30.0, 'material_price': 20.0}], set()))
    monkeypatch.setattr(material_calculation, 'customer_material_quotes', lambda materials, selections, inventory: [
        {'id': 'lamp', 'label': 'Lamp', 'service': 'materials', 'status': 'priced', 'issues': [], 'lines': [],
         'packing_only': Decimal('8'), 'packing_and_material': Decimal('20')}])
    result = package(db)
    assert result['items'][0]['labor_price'] == 0 and result['items'][0]['price'] == 20.0
    assert result['material_quotes'][0]['packing_only'] == 0 and result['material_quotes'][0]['packing_and_material'] == 12
    from routes.pricing import customer_package_lines
    lines = customer_package_lines(result, {'mode': 'none', 'item_ids': ['tv'], 'material_item_ids': ['tv'],
                                            'additional_items': {'lamp': {'service': 'materials'}}})
    assert {line['name']: line['amount'] for line in lines} == {'Lamp Packing': Decimal('12'), 'TV Boxing': Decimal('20')}


def test_local_full_packing_adds_no_line_per_cubic_foot(db):
    from routes.pricing import customer_package_lines
    assert customer_package_lines(package(db), {'mode': 'full'}) == []


def test_full_packing_hours_are_the_ones_the_local_price_adds():
    from local_pricing import LocalCalculation, LocalSettings, calculate_local, full_pack_hours
    quote = calculate_local(LocalSettings(), LocalCalculation(cubic_feet=Decimal('1500'), full_pack=True))
    assert quote['packing_hours'] == full_pack_hours(Decimal('1500')) == 3


@pytest.mark.parametrize('mode,priced', [('full', True), ('none', True), ('partial', False)])
def test_a_local_packing_choice_is_saved_and_the_job_priced_once(db, monkeypatch, mode, priced):
    import json
    from fastapi import HTTPException
    import routes.pricing as pricing
    import routes.public_moves as public_moves
    from models import LeadJob, PricingPlan, PublicMoveAccess
    from datetime import datetime
    db.add(PublicMoveAccess(id='access', lead_id='lead', job_id='job', key_hash='k', request_hash='r', token_hash='t', expires_at=datetime(2030, 1, 1)))
    db.get(LeadJob, 'job').customer_packing_package = json.dumps({'mode': 'none', 'item_ids': ['tv'], 'material_item_ids': ['tv']})
    db.commit()
    monkeypatch.setattr(pricing, 'infer_job_move_type', lambda lead, job, db: ('Local', db.get(PricingPlan, 'plan')))
    calls = []
    monkeypatch.setattr(pricing, 'calculate_and_save_lead_job_price', lambda lead, job, db: calls.append(job.id) or 1)
    body = public_moves.CustomerPackingPatch(change={'kind': 'mode', 'mode': mode})
    if not priced:
        with pytest.raises(HTTPException):
            public_moves._save_packing_change(body, db.get(PublicMoveAccess, 'access'), db)
        assert calls == []
        return
    public_moves._save_packing_change(body, db.get(PublicMoveAccess, 'access'), db)
    saved = json.loads(db.get(LeadJob, 'job').customer_packing_package)
    assert saved['mode'] == mode and calls == ['job']
    assert saved['item_ids'] == ([] if mode == 'full' else ['tv'])
