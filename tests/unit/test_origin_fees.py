import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import httpx
import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
import delivery_fees as fees


def services(rules):
    return [SimpleNamespace(comments=fees.DELIVERY_FEE_PREFIX + json.dumps({'enabled':True,'rules':rules}))]


def rule(**patches):
    return {'state':'VT','zip_codes':[],'origin_zip':'20815','rate_per_mile':'5',**patches}


def test_origin_matching_and_cached_route(monkeypatch):
    route = MagicMock(return_value=160934)
    monkeypatch.setattr(fees, 'driving_meters', route)
    rows = services([rule(), rule(zip_codes=['05401'], rate_per_mile='7')])
    rows[0].comments = rows[0].comments.replace(fees.DELIVERY_FEE_PREFIX, fees.ORIGIN_FEE_PREFIX)
    quote = fees.origin_fee(rows, '05401')
    assert quote['amount'] == 700 and 'to pickup' in quote['description']
    assert fees.origin_fee(rows, '05401', quote)['amount'] == 700
    assert route.call_count == 1
    assert fees.delivery_fee(rows, '05401') is None
    assert fees.origin_fee(rows, '20815') is None
    fees.origin_fee(rows, '05402', quote)
    assert route.call_count == 2


def test_origin_and_destination_saved_and_preview(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import models
    mocks={name:MagicMock() for name in ['auth','database','routes.leads']}
    mocks['auth'].get_current_user=lambda:None
    mocks['auth'].require_admin=lambda:None
    mocks['database'].get_db=lambda:None
    spec=importlib.util.spec_from_file_location('origin_pricing_test',BACKEND/'routes/pricing.py')
    api=importlib.util.module_from_spec(spec)
    mocks['origin_pricing_test']=api
    route=MagicMock(return_value=160934)
    monkeypatch.setattr(fees,'driving_meters',route)
    with patch.dict(sys.modules,mocks):
        spec.loader.exec_module(api)
        engine=create_engine('sqlite://')
        models.Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(models.Company(id='co',name='Test'))
            lead=models.Lead(id='lead',full_name='Test',company_id='co',volume='24')
            job=models.LeadJob(id='job',lead_id='lead',company_id='co',pickup_zip='20850',delivery_zip='05401')
            plan=models.PricingPlan(id='plan',source_key='plan',company_id='co',company_name='Test',name='East',pickup_regions='MD',active=True)
            plan.services=[models.PricingService(name='Destination fees',rate_text='',comments=services([rule()])[0].comments)]
            plan.rates=[models.PricingRate(destination='VT',band_label='286+',cubic_feet_min=286,rate=5,minimum_price=1500)]
            db.add_all([lead,job,plan]);db.commit()
            plan.services.append(models.PricingService(name='Origin fees',rate_text='',comments=
                fees.ORIGIN_FEE_PREFIX + json.dumps({'enabled':True,'rules':[rule(state='MD',rate_per_mile='2')]})))
            db.commit()
            api.ServiceInput(name='Origin fees',comments=plan.services[-1].comments)
            with pytest.raises(ValueError):
                api.ServiceInput(name='Origin fees',comments=fees.ORIGIN_FEE_PREFIX + json.dumps({'rules':[rule(origin_zip='bad')]}))
            assert api.calculate_and_save_lead_job_price(lead,job,db)==2200
            db.commit()
            assert api.calculate_and_save_lead_job_price(lead,job,db)==2200
            db.commit()
            assert route.call_count == 2
            route.assert_any_call('20815','20850')
            route.assert_any_call('20815','05401')
            assert db.query(models.LeadJobCharge).filter_by(name='Origin fees').one().total_cost==200
            assert db.query(models.LeadJobCharge).filter_by(name='Destination fees').one().total_cost==500
            assert set(json.loads(job.customer_packing_package)) >= {'origin_route','delivery_route'}
            preview=api.compute_plan_calculation(plan,api.CalculationInput(destination='VT',pickup_address='20850',delivery_address='05401',cubic_feet=24))
            assert preview['total']==2200
            assert len([c for c in preview['charges'] if c['id']=='origin-mileage'])==1
            monkeypatch.setattr(api,'_plan_or_404',lambda *args:plan)
            missing=api.calculate_pricing(plan.id,api.CalculationInput(destination='VT',delivery_address='05401',cubic_feet=24),None,db)
            assert any(c['name']=='Origin fees' and c.get('pending') for c in missing['charges'])
            job.pickup_zip='05401'
            monkeypatch.setattr(api,'infer_job_move_type',lambda *args:('long distance',plan))
            api.sync_origin_fee(lead,job,db)
            db.commit()
            assert job.price==2000
            assert db.query(models.LeadJobCharge).filter_by(name='Origin fees').count()==0
            assert db.query(models.LeadJobCharge).filter_by(name='Destination fees').one().total_cost==500
        engine.dispose()
