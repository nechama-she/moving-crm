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


def test_specific_rules_and_combined_ranges():
    card = fees.delivery_fee_card(services([rule(),rule(zip_codes=['050XX-051XX','05401'],rate_per_mile='7')]))
    assert fees.matching_rule(card,'05001').rate_per_mile == 7
    assert fees.matching_rule(card,'05401').rate_per_mile == 7
    assert fees.matching_rule(card,'05201').rate_per_mile == 5
    assert fees.matching_rule(card,'20815') is None


@pytest.mark.parametrize('patches', [{'origin_zip':'2081'},{'origin_zip':'208XX'},{'rate_per_mile':'-1'},{'state':'XX'},{'zip_codes':['05999-05000']}])
def test_invalid_rule_rejected(patches):
    with pytest.raises(ValueError): fees.DeliveryFeeRule(**rule(**patches))


def test_route_basis_reused_and_rate_changes_without_rerouting(monkeypatch):
    route = MagicMock(return_value=160934)
    monkeypatch.setattr(fees,'driving_meters',route)
    rows = services([rule()])
    quote = fees.delivery_fee(rows,'05401')
    assert quote['miles'] == '100.00' and quote['amount'] == Decimal('500.00')
    saved = {key: quote[key] for key in ('revision','meters')}
    assert fees.delivery_fee(services([rule(rate_per_mile='7')]),'05401',saved)['amount'] == 700
    assert route.call_count == 1
    fees.delivery_fee(rows,'05402',saved)
    fees.delivery_fee(services([rule(origin_zip='20850')]),'05401',saved)
    assert route.call_count == 3
    assert fees.delivery_fee(rows,'20815') is None
    assert route.call_count == 3


def test_google_driving_request_and_failure_handling(monkeypatch):
    with patch.dict(sys.modules,{'config':SimpleNamespace(get_config=lambda:{'GOOGLE_MAPS_SERVER_KEY':'test-only'})}):
        response = MagicMock()
        response.json.return_value={'routes':[{'distanceMeters':123456}]}
        post=MagicMock(return_value=response)
        monkeypatch.setattr(fees.httpx,'post',post)
        assert fees.driving_meters('20815','123 Main St, Burlington, VT 05401') == 123456
        kwargs=post.call_args.kwargs
        assert kwargs['json']['travelMode']=='DRIVE'
        assert kwargs['json']['origin']=={'address':'20815, USA'}
        assert kwargs['headers']['X-Goog-FieldMask']=='routes.distanceMeters'
        response.json.return_value={'routes':[]}
        with pytest.raises(HTTPException) as error: fees.driving_meters('20815','05401')
        assert error.value.status_code==422
        post.side_effect=httpx.TimeoutException('secret provider details')
        with pytest.raises(HTTPException) as error: fees.driving_meters('20815','05401')
        assert error.value.status_code==502 and 'secret' not in error.value.detail


def test_saved_estimate_and_address_changes(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import models
    mocks={name:MagicMock() for name in ['auth','database','routes.leads']}
    mocks['auth'].get_current_user=lambda:None
    mocks['auth'].require_admin=lambda:None
    mocks['database'].get_db=lambda:None
    spec=importlib.util.spec_from_file_location('delivery_pricing_test',BACKEND/'routes/pricing.py')
    api=importlib.util.module_from_spec(spec)
    mocks['delivery_pricing_test']=api
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
            api.ServiceInput(name='Destination fees',comments=plan.services[0].comments)
            assert api.calculate_and_save_lead_job_price(lead,job,db)==2000
            db.commit()
            assert api.calculate_and_save_lead_job_price(lead,job,db)==2000
            db.commit()
            assert route.call_count==1
            charge=db.query(models.LeadJobCharge).filter_by(name='Destination fees').one()
            assert charge.total_cost==500 and '20815' in charge.description and '100.00 driving miles' in charge.description
            db.expunge(charge)
            job.delivery_zip='20815'
            api.sync_delivery_fee(lead,job,db);db.commit()
            assert job.price==1500 and db.query(models.LeadJobCharge).filter_by(name='Destination fees').count()==0
            assert route.call_count==1
            job.delivery_zip='05402'
            api.sync_delivery_fee(lead,job,db);db.commit()
            assert job.price==2000 and route.call_count==2
            preview=api.compute_plan_calculation(plan,api.CalculationInput(destination='VT',delivery_address='05402',cubic_feet=24))
            assert preview['total']==2000
            assert len([c for c in preview['charges'] if c['id']=='delivery-mileage'])==1
            monkeypatch.setattr(api,'_plan_or_404',lambda *args:plan)
            with pytest.raises(HTTPException) as error:
                api.calculate_pricing(plan.id,api.CalculationInput(destination='VT',cubic_feet=24),None,db)
            assert error.value.status_code==422
            job.delivery_zip='05403'
            route.side_effect=HTTPException(502,'Routing unavailable')
            with pytest.raises(HTTPException): api.calculate_and_save_lead_job_price(lead,job,db)
            assert job.price==2000
            assert db.query(models.LeadJobCharge).filter_by(name='Destination fees').count()==1
        engine.dispose()
