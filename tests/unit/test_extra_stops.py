import sys
from pathlib import Path
from decimal import Decimal
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from extra_stops import StopRate, stop_price, ExtraStopsCard

@pytest.mark.parametrize('miles,total',[(0,0),(8,0),(10,0),(11,55),(15,75),(20,100)])
def test_pickup_allowance(miles,total):
    rule=StopRate(free_miles=10,stop_fee=50,per_mile=5)
    assert stop_price(rule,Decimal(str(miles))*Decimal('1609.344'))['total']==total

@pytest.mark.parametrize('miles,total',[(0,50),(8,90),(15,125)])
def test_delivery_fee(miles,total):
    rule=StopRate(free_miles=0,stop_fee=50,per_mile=5)
    assert stop_price(rule,Decimal(str(miles))*Decimal('1609.344'))['total']==total

def test_parameters_and_partial_mile():
    rule=StopRate(free_miles=5,stop_fee=20,per_mile=2)
    assert stop_price(rule,Decimal('5.5')*Decimal('1609.344')) == {
        'miles': 6, 'billable_miles': 1, 'total': 22}
    assert stop_price(rule,Decimal('3.1')*Decimal('1609.344'))['miles']==4
    assert stop_price(rule,Decimal('4')*Decimal('1609.344'))['miles']==4
    with pytest.raises(ValueError):StopRate(free_miles=-1,stop_fee=50,per_mile=5)


def test_recalculation_uses_updated_zero_allowance_and_keeps_saved_stop(monkeypatch):
    import json
    from types import SimpleNamespace
    from uuid import uuid5, NAMESPACE_URL
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import models
    from extra_stops import EXTRA_STOPS_PREFIX, add_charges, route_revision
    from charge_updates import ChargeUpdates
    origin, address = 'Delivery address', 'Extra delivery address'
    stop_id = str(uuid5(NAMESPACE_URL, f'extra-stop:job:delivery:{address}'))
    saved = {'extra_stops': {'delivery': {'answer': True, 'stops': [
        {'id': stop_id, 'address': address, 'meters': 16093, 'revision': route_revision(origin,address)}]}}}
    card = ExtraStopsCard(enabled=True, pickup=StopRate(free_miles=10,stop_fee=50,per_mile=5),
                          delivery=StopRate(free_miles=5,stop_fee=50,per_mile=5))
    monkeypatch.setitem(sys.modules, 'routes.leads', SimpleNamespace(_read_job_route=lambda *args: ('Pickup',[address],origin)))
    engine = create_engine('sqlite://')
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        lead = models.Lead(id='lead',full_name='Customer')
        job = models.LeadJob(id='job',lead_id='lead',pickup_zip='Pickup',delivery_zip=origin,
            stop_types=json.dumps([{'address':address,'type':'delivery'}]),customer_packing_package=json.dumps(saved))
        plan = models.PricingPlan(id='book',company_name='Company',name='Book',source_key='test')
        service = models.PricingService(id='stops',name='Extra stops',comments=EXTRA_STOPS_PREFIX+card.model_dump_json())
        plan.services.append(service)
        db.add_all([lead,job,plan]);db.commit()
        assert add_charges(lead,job,db,plan) == 75
        db.commit()
        original = db.query(models.LeadJobCharge).one()
        original_id = original.id
        card.delivery.free_miles = Decimal(0)
        service.comments = EXTRA_STOPS_PREFIX + card.model_dump_json()
        db.commit();db.expire_all()
        updates = ChargeUpdates(db,[original],remove_missing=False)
        assert add_charges(lead,job,updates,plan) == 100
        updates.finish();db.commit()
        assert db.query(models.LeadJobCharge).one().id == original_id
        assert original.total_cost == 100
        assert '0 miles free' in original.description
        assert json.loads(job.customer_packing_package)['extra_stops']['delivery'] == saved['extra_stops']['delivery']
    engine.dispose()
