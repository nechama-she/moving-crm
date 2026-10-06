import sys
import ast
import json
from datetime import datetime
from types import SimpleNamespace as Row
from uuid import uuid4
from pathlib import Path
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, Lead, LeadJob, LeadJobCharge
from charge_updates import ChargeUpdates
import models
import pytest


def charge(id, name, amount, order=0):
    return LeadJobCharge(id=id, job_id='job', name=name, description='Calculated',
                         subtotal=amount, discount_amount=0, total_cost=amount, sort_order=order)


def test_recalculation_updates_existing_rows_without_delete_or_insert():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Lead(id='lead', full_name='Customer'), LeadJob(id='job', lead_id='lead'),
                    charge('legacy-base', 'Transportation', 10), charge('packing', 'Packing', 12, 2000)])
        db.commit()
        original = db.get(LeadJobCharge, 'legacy-base')
        created_at = original.created_at
        statements = []
        event.listen(engine, 'before_cursor_execute', lambda conn,cursor,sql,params,context,many: statements.append(sql))
        for amount in (0, 25):
            updates = ChargeUpdates(db, db.query(LeadJobCharge).all(), match_legacy_base=True)
            updates.add(charge('new-random-id', 'Transportation', amount))
            updates.add(charge('packing', 'Packing', amount + 10, 2000))
            updates.finish()
            db.commit()
            assert db.get(LeadJobCharge, 'legacy-base') is original
            assert original.total_cost == Decimal(amount)
            assert original.created_at == created_at
            assert db.query(LeadJobCharge).count() == 2
        assert not any(sql.lstrip().upper().startswith(('DELETE ', 'INSERT ')) for sql in statements)
    engine.dispose()


def test_new_charge_insert_and_explicit_deselection_leave_other_rows_untouched():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Lead(id='lead', full_name='Customer'), LeadJob(id='job', lead_id='lead'),
                    charge('keep', 'Transportation', 100), charge('remove', 'Packing', 12, 2000)])
        db.commit()
        updates = ChargeUpdates(db, [db.get(LeadJobCharge, 'remove')])
        updates.add(charge('new', 'New packing item', 20, 2001))
        updates.finish()
        db.commit()
        assert db.get(LeadJobCharge, 'keep').total_cost == 100
        assert db.get(LeadJobCharge, 'remove') is None
        assert db.get(LeadJobCharge, 'new').total_cost == 20
    engine.dispose()


def test_repricing_omitted_zero_charge_keeps_identity_when_paid_again():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Lead(id='lead',full_name='Customer'), LeadJob(id='job',lead_id='lead'),
                    charge('fuel','Fuel charge',10)])
        db.commit()
        original = db.get(LeadJobCharge,'fuel')
        updates = ChargeUpdates(db,[original],match_legacy_base=True,remove_missing=False)
        updates.finish()
        db.commit()
        assert original.total_cost == 0
        updates = ChargeUpdates(db,[original],match_legacy_base=True,remove_missing=False)
        updates.add(charge('new-random','Fuel charge',20))
        updates.finish()
        db.commit()
        assert db.get(LeadJobCharge,'fuel') is original
        assert original.total_cost == 20
        assert db.query(LeadJobCharge).count() == 1
    engine.dispose()


@pytest.mark.parametrize('move_type', ['Local', 'Long Distance'])
def test_actual_recalculation_keeps_charge_ids_and_answers(monkeypatch, move_type):
    path = Path(__file__).resolve().parents[2] / 'backend/routes/pricing.py'
    node = next(n for n in ast.parse(path.read_text()).body if getattr(n,'name','') == 'calculate_and_save_lead_job_price')
    node.decorator_list = []
    for arg in node.args.args:
        arg.annotation = None
    scope = {name:getattr(models,name) for name in ('PricingPlan','LeadJobCharge','PublicMoveAccess')}
    quote = {'total':100, 'base_price':100, 'match':{'rate':1,'band_label':'All'}, 'charges':[]}
    local_quote = {'total':100, 'charges':[{'name':'Local moving','description':'Labor','subtotal':100,'totalCost':100}]}
    scope.update(Decimal=Decimal, uuid4=uuid4, datetime=datetime, json=json,
                 _rounded_cubic_feet=lambda v:v, delivery_location=lambda a:('MD','20850'),
                 _material_item_names=lambda x:[], _job_spark_inventory_items=lambda *a:[],
                 _bulky_item_charges=lambda *a,**kw:[], _plan_destination_for_delivery=lambda *a:'GA',
                 CalculationInput=lambda **kw:Row(**kw), job_delivery_fee=lambda *a:None,
                 compute_plan_calculation=lambda *a:quote)
    for name in ('add_delivery_fee_charge','add_customer_packing_charges','add_customer_package_charges',
                 'add_customer_shuttle_charge','add_storage_charge','add_stairs_charges',
                 'add_long_carry_charges','add_elevator_charges'):
        scope[name] = lambda *args,**kw:Decimal(0)
    monkeypatch.setitem(sys.modules,'routes.leads',Row(_refresh_lead_estimated_total=lambda *a:None))
    monkeypatch.setitem(sys.modules,'routes.local_pricing',Row(calculate_book_price=lambda *a:local_quote))
    import extra_stops
    monkeypatch.setattr(extra_stops,'add_charges',lambda *a:Decimal(0))
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        plan = models.PricingPlan(id='plan',company_id='company',company_name='Company',name='Book',source_key='test')
        lead = Lead(id='lead',full_name='Customer',volume=100,company_id='company')
        job = LeadJob(id='job',lead_id='lead',company_id='company',customer_packing='{"item":"packing"}',
                      customer_packing_package='{"elevator":{"pickup":{"uses_elevator":true}}}',
                      estimated_materials='[{"name":"Sofa","quantity":1}]')
        name = 'Local moving' if move_type == 'Local' else 'Transportation charge'
        original = charge('original',name,50)
        db.add_all([plan,lead,job,original]); db.commit()
        scope['infer_job_move_type'] = lambda *a:(move_type,plan)
        before = (job.customer_packing,json.loads(job.customer_packing_package),job.estimated_materials)
        statements=[]
        event.listen(engine,'before_cursor_execute',lambda conn,cursor,sql,params,context,many:statements.append(sql))
        for _ in range(2):
            assert scope['calculate_and_save_lead_job_price'](lead,job,db) == 100
            db.commit()
            assert db.get(LeadJobCharge,'original') is original
            assert original.total_cost == 100
            assert (job.customer_packing,json.loads(job.customer_packing_package),job.estimated_materials) == before
        assert not any(sql.lstrip().upper().startswith(('DELETE ', 'INSERT ')) for sql in statements)
    engine.dispose()
