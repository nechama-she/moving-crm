import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, Company, PricingPlan, PricingRate, PricingRule, PricingService, AppSetting, LocalPricingRoute
from migrate_movers95_pricing import copy_pricing, MARKER, PICKUP_STATES
from pickup_areas import pickup_areas


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Company(id='source', name='Gorilla Haulers'), Company(id='target', name='Movers 95')])
        session.flush()
        session.add(PricingPlan(id='east', company_id='source', company_name='Gorilla Haulers',
            name='East', source_key='original', pickup_regions='NY', fuel_percent=12,
            item_materials='{"rows": []}', price_valid_days=14,
            rates=[PricingRate(destination='FL', band_label='all', rate=4)],
            rules=[PricingRule(title='Rule', description='Keep this')],
            services=[PricingService(name='Packing', rate_text='2')]))
        session.add(LocalPricingRoute(company_id='source', pickup='MD', delivery='VA'))
        session.commit()
        yield session


def test_copy_preserves_settings_and_runs_once(db):
    db.add(AppSetting(key='local_pricing:east', value='{"custom": "preserved"}'))
    db.commit()
    result = copy_pricing(db)
    db.commit()
    target = db.get(PricingPlan, result['target_plan_id'])
    source = db.get(PricingPlan, 'east')
    assert [area['state'] for area in pickup_areas(target.pickup_regions)] == PICKUP_STATES
    for field in ('fuel_percent', 'item_materials', 'price_valid_days', 'active'):
        assert getattr(target, field) == getattr(source, field)
    for relation in ('rates', 'rules', 'services'):
        original, copied = getattr(source, relation)[0], getattr(target, relation)[0]
        assert original.id != copied.id
        for column in original.__table__.columns:
            if column.name not in {'id', 'plan_id'}:
                assert getattr(original, column.name) == getattr(copied, column.name)
    assert db.get(AppSetting, f'local_pricing:{target.id}').value == '{"custom": "preserved"}'
    assert db.query(LocalPricingRoute).filter_by(company_id='target').one().delivery == 'VA'
    target.fuel_percent = 20
    db.commit()
    assert copy_pricing(db)['status'] == 'already applied'
    assert target.fuel_percent == 20
    assert source.pickup_regions == 'NY'


def test_dry_run_rolls_back_and_defaults_are_copied(db):
    result = copy_pricing(db)
    assert db.get(AppSetting, f"local_pricing:{result['target_plan_id']}") is not None
    db.rollback()
    assert db.get(AppSetting, MARKER) is None
    assert db.query(PricingPlan).filter_by(company_id='target').count() == 0
    assert db.query(LocalPricingRoute).filter_by(company_id='target').count() == 0


def test_existing_book_updated_in_place(db):
    db.add(PricingPlan(id='existing', company_id='target', company_name='Movers 95',
        name='MD , VA , DC , DE', source_key='existing-import',
        services=[PricingService(name='Old service', rate_text='99')]))
    db.add(AppSetting(key='local_pricing:existing', value='{}'))
    db.add(LocalPricingRoute(company_id='target', pickup='MD', delivery='VA'))
    db.commit()
    result = copy_pricing(db)
    db.commit()
    assert result['target_plan_id'] == 'existing'
    target = db.get(PricingPlan, 'existing')
    assert target.source_key == 'existing-import'
    assert target.name == 'MD, VA, DC, DE, PA'
    assert [area['state'] for area in pickup_areas(target.pickup_regions)] == PICKUP_STATES
    assert [service.name for service in target.services] == ['Packing']
    assert db.query(PricingPlan).filter_by(company_id='target').count() == 1
    assert db.query(LocalPricingRoute).filter_by(company_id='target').count() == 1


def test_deployment_transaction_can_rollback_copy(db):
    with db.bind.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection) as session:
            copy_pricing(session)
            session.commit()
        transaction.rollback()
    db.expire_all()
    assert db.get(AppSetting, MARKER) is None
    assert db.query(PricingPlan).filter_by(company_id='target').count() == 0


def test_every_pricing_card_configuration_is_copied(db):
    import json
    source = db.get(PricingPlan, 'east')
    prefixes = ['__extra_stops__:', '__elevator_pricing__:', '__long_carry_pricing__:',
        '__stairs_pricing__:', '__storage_periods__:', '__origin_mileage__:',
        '__delivery_mileage__:', '__delivery_shuttle__:', '__ld_packing__:']
    for index, prefix in enumerate(prefixes):
        source.services.append(PricingService(name=prefix, rate_text=str(index),
            comments=prefix + json.dumps({'enabled': True, 'rate': index,
                'materials': [{'item_id': 'material', 'price': 12}], 'items': []}), sort_order=index))
    source.item_materials = json.dumps({'rows': [{'item_id': 'chair', 'materials': ['material']}],
        'protection_review': [{'item_id': 'glass', 'reason': 'Fragile'}]})
    db.commit()
    result = copy_pricing(db)
    db.commit()
    target = db.get(PricingPlan, result['target_plan_id'])
    assert sorted((s.name, s.rate_text, s.comments, s.sort_order) for s in target.services) == sorted(
        (s.name, s.rate_text, s.comments, s.sort_order) for s in source.services)
    assert target.item_materials == source.item_materials
    assert all(any(s.comments.startswith(prefix) for s in target.services) for prefix in prefixes)
