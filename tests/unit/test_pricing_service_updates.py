import sys
from pathlib import Path
from types import SimpleNamespace as Row
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from pricing_service_updates import prepare_service_updates


def test_price_edit_preserves_identity_and_customer_answer():
    original = Row(id='original', name='Piano', rate_text='50', comments='old')
    answers = {'original:1':'packing'}
    row = Row(id='original', name='Piano', rate_text='75', comments='new')
    updates = prepare_service_updates([original], [row])
    assert updates[0][0] is original
    assert answers[f'{updates[0][0].id}:1'] == 'packing'
    assert original.rate_text == '50'  # Validation does not mutate stored rows.


def test_legacy_client_reuses_name_and_reorder_rename_keeps_ids():
    a,b=Row(id='a',name='A'),Row(id='b',name='B')
    assert prepare_service_updates([a,b],[Row(id=None,name='A')])[0][0] is a
    assert [item.id for item,_ in prepare_service_updates([a,b],[Row(id='b',name='Renamed'),Row(id='a',name='A')])] == ['b','a']
    assert prepare_service_updates([a],[Row(id=None,name='New')])[0][0] is None


@pytest.mark.parametrize('incoming', [[Row(id='foreign',name='A')],[Row(id='a',name='A'),Row(id='a',name='A')],[Row(id='a',name=' ')]])
def test_invalid_save_rejected_without_mutation(incoming):
    original=Row(id='a',name='A')
    with pytest.raises(HTTPException):
        prepare_service_updates([original],incoming)
    assert original.name=='A'


def test_real_pricing_save_keeps_service_and_client_data():
    import ast
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import models
    from fastapi import Depends
    path=Path(__file__).resolve().parents[2] / 'backend/routes/pricing.py'
    node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if getattr(n,'name','')=='update_pricing_plan')
    node.decorator_list=[]
    scope={name:getattr(models,name) for name in ('PricingPlan','PricingRule','PricingRate','PricingService','User')}
    from pickup_areas import set_pickup_areas
    from extra_stops import EXTRA_STOPS_PREFIX, ExtraStopsCard, save_stops_card
    from elevator_pricing import ELEVATOR_PREFIX, ElevatorCard, save_elevator_card
    from long_carry_pricing import LONG_CARRY_PREFIX, LongCarryCard, save_long_carry_card
    from stairs_pricing import STAIRS_PREFIX, StairsCard, save_stairs_card
    from storage_pricing import STORAGE_PREFIX, StorageCard, save_storage_card
    from shuttle import SHUTTLE_PREFIX, ShuttleCard, save_shuttle_card
    from delivery_fees import ORIGIN_FEE_PREFIX, DELIVERY_FEE_PREFIX, DeliveryFeeCard, save_fee_card
    from bulky_items import is_bulky_row, save_bulky_items
    from long_distance_packing import PACKING_CARD_PREFIX, PackingCard, save_packing_card
    from datetime import datetime, timezone
    scope.update(datetime=datetime,timezone=timezone,PlanUpdate=Row,Session=Session,Depends=Depends,require_admin=lambda:None,get_db=lambda:None,HTTPException=HTTPException,json=json,
                 set_pickup_areas=set_pickup_areas,EXTRA_STOPS_PREFIX=EXTRA_STOPS_PREFIX,ExtraStopsCard=ExtraStopsCard,save_stops_card=save_stops_card,
                 ELEVATOR_PREFIX=ELEVATOR_PREFIX,ElevatorCard=ElevatorCard,save_elevator_card=save_elevator_card,
                 LONG_CARRY_PREFIX=LONG_CARRY_PREFIX,LongCarryCard=LongCarryCard,save_long_carry_card=save_long_carry_card,
                 STAIRS_PREFIX=STAIRS_PREFIX,StairsCard=StairsCard,save_stairs_card=save_stairs_card,
                 STORAGE_PREFIX=STORAGE_PREFIX,StorageCard=StorageCard,save_storage_card=save_storage_card,
                 SHUTTLE_PREFIX=SHUTTLE_PREFIX,ShuttleCard=ShuttleCard,save_shuttle_card=save_shuttle_card,
                 ORIGIN_FEE_PREFIX=ORIGIN_FEE_PREFIX,DELIVERY_FEE_PREFIX=DELIVERY_FEE_PREFIX,DeliveryFeeCard=DeliveryFeeCard,save_fee_card=save_fee_card,
                 is_bulky_row=is_bulky_row,save_bulky_items=save_bulky_items,
                 PACKING_CARD_PREFIX=PACKING_CARD_PREFIX,PackingCard=PackingCard,save_packing_card=save_packing_card)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
    engine=create_engine('sqlite://')
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        plan=models.PricingPlan(id='plan',company_name='Company',name='Book',source_key='test')
        service=models.PricingService(id='original',name='Piano',rate_text='50',comments='')
        plan.services.append(service)
        plan.rules.append(models.PricingRule(id='rule', category='general', title='Rule', description='Old'))
        plan.rates.append(models.PricingRate(id='rate', destination='GA', band_label='All', rate=10))
        lead=models.Lead(id='lead',full_name='Customer')
        job=models.LeadJob(id='job',lead_id='lead',customer_packing='{"original:1":"packing"}',
                           customer_packing_package='{"elevator":{"pickup":{"uses_elevator":true}},"item_ids":["box:1"]}',
                           estimated_materials='[{"name":"Piano","quantity":1}]')
        db.add_all([plan,lead,job]);db.commit()
        before=(job.customer_packing,job.customer_packing_package,job.estimated_materials)
        rate=Row(id='rate',destination='GA',destination_group='',minimum_price=None,minimum_text='',band_label='All',cubic_feet_min=0,cubic_feet_max=None,rate=0,rate_text='0')
        rule=Row(id='rule',category='general',title='Renamed',description='New')
        body=Row(name='Book',pickup_areas=None,pickup_regions='',fuel_percent=10,active=True,rules=[rule],rates=[rate],
                 services=[Row(id='original',name='Piano',rate_text='75',comments='')])
        from sqlalchemy import event
        writes=[]
        event.listen(engine, 'before_cursor_execute', lambda conn,cursor,statement,parameters,context,many: writes.append(statement))
        for _ in range(2):
            scope['update_pricing_plan']('plan',body,Row(),db)
            db.expire_all()
            assert db.get(models.PricingService,'original').rate_text=='75'
            assert db.query(models.PricingService).count()==1
            assert db.get(models.PricingRate,'rate').rate==0
            assert db.get(models.PricingRule,'rule').title=='Renamed'
            assert (job.customer_packing,job.customer_packing_package,job.estimated_materials)==before
            assert db.get(models.Lead,'lead').full_name=='Customer'
        assert not any(sql.lstrip().upper().startswith(('DELETE ', 'INSERT ')) for sql in writes)
    engine.dispose()
