import sys
from pathlib import Path
from decimal import Decimal
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from shuttle import ShuttleCard, ShuttleArea, area_matches, shuttle_option, zip_bounds


@pytest.mark.parametrize('rule,expected', [('13544', (13544,13544)), ('111XX-12XXX',(11100,12999)), ('005XX',(500,599)), ('11100–12000',(11100,12000))])
def test_zip_bounds(rule, expected):
    assert zip_bounds(rule) == expected


@pytest.mark.parametrize('rule', ['12', '123456', '12X45', 'XXXXX', '99999-10000', '111XX-12XXX-14000'])
def test_invalid_zip_rules(rule):
    with pytest.raises(ValueError): zip_bounds(rule)


def test_state_and_zip_matching():
    areas = [ShuttleArea(state='ny', zip_codes=['111XX-12XXX','13544'])]
    for zip_code in ['11100','12999','13544']:
        assert area_matches(areas, 'NY', zip_code)
    for zip_code in ['11099','13000','13545','']:
        assert not area_matches(areas, 'NY', zip_code)
    assert not area_matches(areas, 'NJ', '11100')
    assert area_matches([ShuttleArea(state='NJ')], 'NJ', '')


def test_minimum_answer_and_address_invalidation():
    card = ShuttleCard(enabled=True, rate=Decimal('1.50'), access_distance_ft=500)
    def option(saved={}, address='NY 13544', config=card, volume=24):
        return shuttle_option(config,address,'NY','13544',volume,286,saved)
    first = option()
    assert first['answer'] is None and not first['required']
    assert first['total'] == 429 and first['cubic_feet'] == 286
    saved = {'answer':False,'revision':first['revision']}
    assert option(saved)['required']
    assert not option({'answer':True,'revision':first['revision']})['required']
    assert option(saved,address='Other address NY 13544')['answer'] is None
    assert option(saved,config=card.model_copy(update={'access_distance_ft':300}))['answer'] is None
    assert option(volume=400)['total'] == 600
    assert option(config=card.model_copy(update={'minimum_cubic_feet':100}))['total'] == 150
    automatic = option(config=card.model_copy(update={'areas':[ShuttleArea(state='NY')]}))
    assert automatic['required'] and automatic['automatic']
    assert option(config=card.model_copy(update={'enabled':False})) is None


def test_saved_book_automatically_prices_matching_delivery_only():
    import importlib.util
    import json
    from unittest.mock import MagicMock, patch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import models
    from shuttle import SHUTTLE_PREFIX
    backend = Path(__file__).resolve().parents[2] / 'backend'
    mocks = {name: MagicMock() for name in ['auth','database','routes.leads']}
    mocks['auth'].get_current_user = lambda: None
    mocks['auth'].require_admin = lambda: None
    mocks['database'].get_db = lambda: None
    spec = importlib.util.spec_from_file_location('shuttle_pricing_test',backend / 'routes/pricing.py')
    api = importlib.util.module_from_spec(spec)
    mocks['shuttle_pricing_test'] = api
    with patch.dict(sys.modules,mocks):
        spec.loader.exec_module(api)
        engine = create_engine('sqlite://')
        models.Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(models.Company(id='company',name='Test'))
            lead = models.Lead(id='lead',full_name='Test',company_id='company',volume='24')
            job = models.LeadJob(id='job',lead_id='lead',company_id='company',pickup_zip='20850',delivery_zip='13544')
            config = ShuttleCard(enabled=True,rate='1.50',access_distance_ft=450,
                                 areas=[ShuttleArea(state='NY',zip_codes=['111XX-12XXX','13544'])])
            plan = models.PricingPlan(id='plan',source_key='plan',company_id='company',company_name='Test',name='East',source_file='',source_sheet='',pickup_regions='MD',active=True)
            plan.services = [models.PricingService(name='Delivery shuttle',rate_text='',comments=SHUTTLE_PREFIX+config.model_dump_json())]
            plan.rates = [models.PricingRate(destination='NY',band_label='286+',cubic_feet_min=286,rate=5,minimum_price=1500)]
            db.add_all([lead,job,plan]);db.commit();db.expire_all()
            # API validation and DB storage use the same config; no separate table needed.
            api.ServiceInput(name='Delivery shuttle',comments=plan.services[0].comments)
            invalid = config.model_dump(mode='json');invalid['areas'][0]['zip_codes']=['99999-10000']
            with pytest.raises(ValueError):
                api.ServiceInput(name='Delivery shuttle',comments=SHUTTLE_PREFIX+json.dumps(invalid))
            body = api.CalculationInput(destination='NY',delivery_address='13544',cubic_feet=24)
            quote = api.compute_plan_calculation(plan,body)
            assert quote['total'] == 1929
            assert len([c for c in quote['charges'] if c['name']=='Delivery shuttle']) == 1
            assert api.calculate_and_save_lead_job_price(lead,job,db) == 1929
            db.commit()
            assert db.query(models.LeadJobCharge).filter_by(job_id=job.id,name='Delivery shuttle').one().total_cost == 429
            job.delivery_zip='13000'
            assert api.calculate_and_save_lead_job_price(lead,job,db) == 1500
            db.commit()
            assert db.query(models.LeadJobCharge).filter_by(job_id=job.id,name='Delivery shuttle').count() == 0
            assert api.customer_shuttle(lead,job,db)['answer'] is None
        engine.dispose()
