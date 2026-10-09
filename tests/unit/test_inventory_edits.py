"""Stable-ID edits, sparse writes, joined names, and optimistic concurrency."""
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from test_public_moves import portal, manual_catalog
import models
from inventory_edits import InventoryEdits, load_inventory_editor, save_inventory_edits


def setup_inventory(fixture, active=True):
    _, db, lead, access = fixture
    rows = [dict(name='Chair',room='Bedroom',amount=1,cuft=10,unit_cuft=10,weight=70,catalog_item_id='chair'),
            dict(name='Chair',room='Bedroom',amount=1,cuft=10,unit_cuft=10,weight=70,catalog_item_id='chair')]
    rooms = [dict(name='Bedroom',room_type_id='bedroom',items=rows)]
    details = dict(last_spark_id='report',last_spark_status='completed',spark_inventory_snapshot=rows,manual_rooms=rooms) if active else dict(inventory_draft=dict(rows=rows,rooms=rooms))
    saved = models.LeadLiveSwitch(lead_id=lead.id,details=json.dumps(details))
    db.add(saved)
    if active:
        for index,row in enumerate(rows):
            db.add(models.LeadSparkInventoryItem(id=str(uuid4()),job_id=access.job_id,sort_order=index,name='Chair',amount=1,cuft=10))
    db.commit()
    editor = load_inventory_editor(access,db)
    return db,lead,access,saved,editor


def body(editor, **edits):
    return InventoryEdits(request_id=uuid4(),revision=editor['revision'],report_id=editor['report_id'],**edits)


@pytest.mark.parametrize('active', [True, False])
def test_service_prices_use_configured_rate_quantity_and_default(manual_catalog, active):
    from types import SimpleNamespace
    from item_selectors import ItemSelectorsInput, add_service_charges
    from charge_updates import ChargeUpdates
    db, lead, access, saved, _ = setup_inventory(manual_catalog, active)
    job = db.get(models.LeadJob, access.job_id)
    config = ItemSelectorsInput(rows=[dict(id='service', item_id='chair', options=['Owner', 'Movers'],
                                         default='Owner', prices=[0, '73.25'])])
    plan = SimpleNamespace(item_selectors=json.dumps(config.model_dump(mode='json')['rows']))
    details = json.loads(saved.details)
    rows = details['spark_inventory_snapshot'] if active else details['inventory_draft']['rows']
    rows[0].update(amount=2, selections={'service': 'Movers'})
    rows[1].update(amount=3)  # Unselected items use the free default.

    def calculate():
        saved.details = json.dumps(details)
        db.flush()
        updates = ChargeUpdates(db, db.query(models.LeadJobCharge).filter_by(job_id=job.id).all())
        total = add_service_charges(lead, job, updates, plan)
        updates.finish()
        return total

    assert calculate() == Decimal('146.50')
    charge = db.query(models.LeadJobCharge).filter_by(job_id=job.id).one()
    charge_id = charge.id
    assert '73.25 per item' in charge.description
    assert calculate() == Decimal('146.50')
    assert db.query(models.LeadJobCharge).filter_by(job_id=job.id).one().id == charge_id
    rows[0]['amount'] = 4
    assert calculate() == Decimal('293.00')
    rows[0]['going'] = False
    assert calculate() == 0
    assert db.query(models.LeadJobCharge).filter_by(job_id=job.id).count() == 0
    rows[0].update(going=True, selections={'service': 'Owner'})
    assert calculate() == 0
    config.rows[0].default = 'Movers'
    plan.item_selectors = json.dumps(config.model_dump(mode='json')['rows'])
    assert calculate() == Decimal('219.75')  # Only the three defaulted units.
    plan.item_selectors = '[]'
    assert calculate() == 0


def test_service_option_prices_are_optional_and_validated():
    from item_selectors import ItemSelectorsInput
    row = dict(id='service', item_id='tv', options=['Owner', 'Movers'], default='Owner')
    assert ItemSelectorsInput(rows=[row]).rows[0].prices == [None, None]
    for prices in ([-1, 0], ['1.001', 0], [0]):
        with pytest.raises(ValueError):
            ItemSelectorsInput(rows=[dict(row, prices=prices)])


def test_reusable_service_attachments_share_options_and_prices(manual_catalog, monkeypatch):
    import sys
    from types import SimpleNamespace
    from item_selectors import ItemSelectorsInput, save_selectors, inventory_selectors, add_service_charges
    from charge_updates import ChargeUpdates
    db, lead, access, saved, _ = setup_inventory(manual_catalog)
    db.add(models.InventoryCatalogItem(id='tv', name='TV', cuft=10, weight=0))
    db.add(models.Company(id='services-company', name='Services'))
    plan = models.PricingPlan(id='shared', company_name='Services', name='Shared', source_key='shared')
    db.add(plan)
    job = db.get(models.LeadJob, access.job_id)
    job.company_id = 'services-company'
    db.commit()
    monkeypatch.setitem(sys.modules, 'routes.pricing', SimpleNamespace(infer_job_move_type=lambda *args: ('Local', plan)))
    config = ItemSelectorsInput(rows=[dict(id='shared-service', item_ids=['chair','tv'], label='Handling',
                                        options=['Owner','Movers'], default='Movers', prices=[0, '12.50'])])
    result = save_selectors(plan, config, db)
    assert len(result['rows']) == 1
    assert result['rows'][0]['item_ids'] == ['chair','tv']
    assert inventory_selectors(access, db)['chair'] == inventory_selectors(access, db)['tv']
    details = json.loads(saved.details)
    details['spark_inventory_snapshot'][1].update(catalog_item_id='tv', name='TV', amount=2)
    saved.details = json.dumps(details)
    db.flush()
    def total():
        updates = ChargeUpdates(db, db.query(models.LeadJobCharge).filter_by(job_id=job.id).all())
        amount = add_service_charges(lead, job, updates, plan)
        updates.finish()
        return amount
    assert total() == Decimal('37.50')
    config.rows[0].prices[1] = Decimal('20')
    save_selectors(plan, config, db)
    assert total() == Decimal('60')
    config.rows[0].item_ids = ['tv']
    save_selectors(plan, config, db)
    assert 'chair' not in inventory_selectors(access, db)
    assert total() == Decimal('40')


@pytest.mark.parametrize('active', [True, False])
def test_item_selectors_persist_per_row(manual_catalog, active, monkeypatch):
    import sys
    from types import SimpleNamespace
    from item_selectors import ItemSelectorsInput, save_selectors, selector_setup
    from manual_inventory import catalog as inventory_catalog
    db, _, access, saved, editor = setup_inventory(manual_catalog, active)
    plan = models.PricingPlan(id='sheet', company_name='Test', name='Sheet', source_key='sheet')
    other = models.PricingPlan(id='other', company_name='Test', name='Other sheet', source_key='other')
    db.add_all([plan, other, models.Company(id='selector-company', name='Test')])
    db.get(models.LeadJob, access.job_id).company_id = 'selector-company'
    db.commit()
    monkeypatch.setitem(sys.modules, 'routes.pricing', SimpleNamespace(infer_job_move_type=lambda *args: ('Local', plan)))
    save_selectors(plan, ItemSelectorsInput(rows=[dict(id='service', item_id='chair', label='Service', options=['Owner', 'Movers'])]), db)
    assert selector_setup(other, db)['rows'] == []
    assert next(row for row in inventory_catalog(db, access)['items'] if row['id'] == 'chair')['selectors'][0]['label'] == 'Service'
    editor = load_inventory_editor(access, db)
    first, second = editor['rooms'][0]['custom_items']
    assert first['selectors'][0]['label'] == 'Service'
    save_inventory_edits(body(editor, update=[dict(id=first['id'], fields={'selections': {'service': 'Movers'}})]), access, db)
    # Rebuild from the report/draft snapshot as well as reopening persisted rows.
    db.get(models.InventoryEditState, access.job_id).source_hash = 'changed'
    db.commit()
    editor = load_inventory_editor(access, db)
    rows = {row['id']: row for row in editor['rooms'][0]['custom_items']}
    assert rows[first['id']]['selections'] == {'service': 'Movers'}
    assert rows[second['id']]['selections'] == {}
    plan.item_selectors = json.dumps([dict(id='service', item_id='chair', label='Service', options=['Owner'])])
    db.commit()
    with pytest.raises(HTTPException) as error:
        save_inventory_edits(body(editor, update=[dict(id=second['id'], fields={'selections': {'service': 'Movers'}})]), access, db)
    assert error.value.status_code == 422
    db.rollback()
    save_inventory_edits(body(editor, update=[dict(id=first['id'], fields={'quantity': 2})]), access, db)
    assert json.loads(db.get(models.InventoryEditItem, first['id']).selections) == {'service': 'Movers'}
    monkeypatch.setitem(sys.modules, 'routes.pricing', SimpleNamespace(infer_job_move_type=lambda *args: ('Local', other)))
    assert all(not row['selectors'] for row in inventory_catalog(db, access)['items'])
    assert all(not row['selectors'] for row in load_inventory_editor(access, db)['rooms'][0]['custom_items'])


@pytest.mark.parametrize('active',[True,False])
def test_id_edit_targets_one_of_identical_items_and_joins_names(manual_catalog,active):
    db,lead,access,saved,editor = setup_inventory(manual_catalog,active)
    room = editor['rooms'][0]
    a,b = room['custom_items']
    assert a['id'] != b['id']
    assert all(row.name is None for row in db.query(models.InventoryEditItem))
    assert load_inventory_editor(access,db) == editor
    statements=[]
    def capture(conn,cursor,sql,params,context,many):statements.append(sql)
    event.listen(db.bind,'before_cursor_execute',capture)
    try:
        request=body(editor,update=[dict(id=a['id'],fields={'quantity':4})])
        response=save_inventory_edits(request,access,db)
    finally:event.remove(db.bind,'before_cursor_execute',capture)
    assert db.get(models.InventoryEditItem,a['id']).quantity==4
    assert db.get(models.InventoryEditItem,b['id']).quantity==1
    assert not any('FROM inventory_catalog_items' in sql for sql in statements)
    item_updates=[sql for sql in statements if sql.startswith('UPDATE inventory_edit_items')]
    assert len(item_updates)==1 and 'quantity=' in item_updates[0] and 'name=' not in item_updates[0]
    if active:
        writes=[sql for sql in statements if sql.startswith('UPDATE lead_spark_inventory_items')]
        assert len(writes)==1 and 'amount=' in writes[0] and 'name=' not in writes[0]
        assert lead.volume==50
    assert save_inventory_edits(request,access,db)==response
    db.get(models.InventoryCatalogItem,'chair').name='Updated chair'
    db.commit()
    loaded=load_inventory_editor(access,db)
    assert loaded['rooms'][0]['custom_items'][0]['name']=='Updated chair'
    assert loaded['revision']==response['revision']


def test_packing_and_room_rename_are_updates_not_delete_add(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    room=editor['rooms'][0];item=room['custom_items'][0]
    response=save_inventory_edits(body(editor,update=[dict(id=item['id'],fields={'mover_pack':True})],
        rooms=dict(update=[dict(id=room['id'],name='Office')])),access,db)
    loaded=load_inventory_editor(access,db)
    assert loaded['rooms'][0]['id']==room['id']
    assert loaded['rooms'][0]['name']=='Office'
    assert loaded['rooms'][0]['custom_items'][0]['id']==item['id']
    assert db.get(models.InventoryEditItem,item['id']).name is None
    assert db.get(models.LeadSparkInventoryItem,item['id']) is not None
    assert loaded['revision']==response['revision']


def test_stale_revision_and_foreign_ids_do_not_modify_inventory(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    item=editor['rooms'][0]['custom_items'][0]
    save_inventory_edits(body(editor,update=[dict(id=item['id'],fields={'quantity':2})]),access,db)
    with pytest.raises(HTTPException) as error:
        save_inventory_edits(body(editor,update=[dict(id=item['id'],fields={'quantity':3})]),access,db)
    assert error.value.status_code==409
    assert 'editor revision mismatch' in error.value.detail
    assert editor['revision'] in error.value.detail
    db.rollback()
    current=load_inventory_editor(access,db)
    with pytest.raises(HTTPException):
        save_inventory_edits(body(current,delete=[uuid4()]),access,db)
    db.rollback()
    assert db.get(models.InventoryEditItem,item['id']).quantity==2


def test_add_delete_going_and_custom_override(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    room=editor['rooms'][0];new_id=str(uuid4())
    save_inventory_edits(body(editor,add=[dict(id=new_id,room_id=room['id'],catalog_item_id='chair',quantity=3)]),access,db)
    assert db.get(models.InventoryEditItem,new_id).name is None
    assert db.get(models.LeadSparkInventoryItem,new_id).amount==3
    current=load_inventory_editor(access,db)
    save_inventory_edits(body(current,update=[dict(id=new_id,fields={'going':False,'name':'My special chair'})]),access,db)
    assert db.get(models.LeadSparkInventoryItem,new_id) is None
    assert db.get(models.InventoryEditItem,new_id).name=='My special chair'
    current=load_inventory_editor(access,db)
    save_inventory_edits(body(current,update=[dict(id=new_id,fields={'going':True})]),access,db)
    assert db.get(models.LeadSparkInventoryItem,new_id).name=='My special chair'
    current=load_inventory_editor(access,db)
    save_inventory_edits(body(current,rooms={'delete':[room['id']]}),access,db)
    assert db.query(models.InventoryEditItem).count()==0
    assert db.query(models.LeadSparkInventoryItem).count()==0
    assert lead.volume==0
    assert load_inventory_editor(access,db)['rooms']==[]


def test_external_report_edit_invalidates_editor(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    details=json.loads(saved.details)
    details['spark_inventory_snapshot'][0]['amount']=8
    saved.details=json.dumps(details);db.commit()
    with pytest.raises(HTTPException) as error: save_inventory_edits(body(editor,delete=[editor['rooms'][0]['custom_items'][0]['id']]),access,db)
    assert 'snapshot changed outside this editor revision' in error.value.detail
    assert 'editor revision mismatch' not in error.value.detail
    db.rollback()


def test_report_conflict_identifies_report_ids(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    request=body(editor)
    request.report_id='different-report'
    with pytest.raises(HTTPException) as error:
        save_inventory_edits(request,access,db)
    assert error.value.status_code==409
    assert 'report mismatch (sent different-report, current report)' in error.value.detail
    assert 'editor revision mismatch' not in error.value.detail
    db.rollback()


def test_batch_rejects_unknown_fields():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        InventoryEdits(request_id=uuid4(),revision=uuid4(),update=[dict(id=uuid4(),fields={'job_id':'other'})])


def test_fresh_draft_create_reload_and_partial_update(manual_catalog):
    _,db,lead,access=manual_catalog
    editor=load_inventory_editor(access,db)
    room_id,item_id=str(uuid4()),str(uuid4())
    save_inventory_edits(body(editor,rooms={'add':[dict(id=room_id,name='Bedroom',room_type_id='bedroom')]},
        add=[dict(id=item_id,room_id=room_id,catalog_item_id='chair',quantity=2)]),access,db)
    loaded=load_inventory_editor(access,db)
    assert loaded['rooms'][0]['id']==room_id
    assert loaded['rooms'][0]['custom_items'][0]['id']==item_id
    save_inventory_edits(body(loaded,update=[dict(id=item_id,fields={'quantity':7})]),access,db)
    saved=db.get(models.LeadLiveSwitch,lead.id)
    assert json.loads(saved.details)['inventory_draft']['cuft']==70
    assert db.query(models.LeadSparkInventoryItem).count()==0
    from manual_inventory import ManualInventoryInput,build_inventory
    draft=json.loads(saved.details)['inventory_draft']
    assert build_inventory(ManualInventoryInput.model_validate(draft['body']),db)[2]==70


def test_foreign_keys_and_duplicate_room_names_remain_distinct(manual_catalog):
    from sqlalchemy import text
    _,db,lead,access=manual_catalog
    db.execute(text('PRAGMA foreign_keys=ON'))
    editor=load_inventory_editor(access,db)
    r1,r2,i1,i2=[str(uuid4()) for _ in range(4)]
    save_inventory_edits(body(editor,rooms={'add':[
        dict(id=r1,name='Bedroom',room_type_id='bedroom'),dict(id=r2,name='Bedroom',room_type_id='bedroom')]},
        add=[dict(id=i1,room_id=r1,name='Custom chair',quantity=1,cuft=3),
             dict(id=i2,room_id=r2,name='Custom chair',quantity=1,cuft=3)]),access,db)
    loaded=load_inventory_editor(access,db)
    assert {room['id'] for room in loaded['rooms']}=={r1,r2}
    # Simulate a legacy producer changing snapshot metadata and forcing re-import.
    saved=db.get(models.LeadLiveSwitch,lead.id)
    details=json.loads(saved.details);details['inventory_draft']['rows'][0]['weight']=2
    saved.details=json.dumps(details);db.commit()
    loaded=load_inventory_editor(access,db)
    assert {room['id'] for room in loaded['rooms']}=={r1,r2}
    assert {item['id'] for room in loaded['rooms'] for item in room['custom_items']}=={i1,i2}


def test_receipt_cannot_be_reused_with_different_fields(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    item=editor['rooms'][0]['custom_items'][0]
    request=body(editor,update=[dict(id=item['id'],fields={'quantity':2})])
    save_inventory_edits(request,access,db)
    request.update[0].fields.quantity=3
    with pytest.raises(HTTPException) as error:save_inventory_edits(request,access,db)
    assert error.value.status_code==409
    assert db.get(models.InventoryEditItem,item['id']).quantity==2


def test_cuft_only_update_preserves_quantity_packing_and_sibling(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    a,b=editor['rooms'][0]['custom_items']
    save_inventory_edits(body(editor,update=[dict(id=a['id'],fields={'cuft':12})]),access,db)
    row=db.get(models.InventoryEditItem,a['id'])
    assert row.unit_cuft==12 and row.quantity==1 and row.going
    assert row.mover_pack is None and row.name is None
    assert db.get(models.InventoryEditItem,b['id']).unit_cuft==10
    assert db.get(models.LeadSparkInventoryItem,a['id']).cuft==12
    assert lead.volume==22


def test_failed_batch_rolls_back_all_edits(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    a,b=editor['rooms'][0]['custom_items']
    with pytest.raises(HTTPException):
        save_inventory_edits(body(editor,update=[dict(id=a['id'],fields={'quantity':4}),
            dict(id=b['id'],fields={'room_id':str(uuid4())})]),access,db)
    db.rollback()
    assert db.get(models.InventoryEditItem,a['id']).quantity==1
    assert load_inventory_editor(access,db)['revision']==editor['revision']


def test_actual_other_moves_row_id_is_rejected(manual_catalog):
    db,lead,access,saved,editor=setup_inventory(manual_catalog)
    other_job=models.LeadJob(id='other-job',lead_id=lead.id,job_order=2)
    other_room=models.InventoryEditRoom(id=str(uuid4()),job_id='other-job',name='Other',room_type_id='bedroom')
    db.add(other_job);db.add(other_room);db.commit()
    other=models.InventoryEditItem(id=str(uuid4()),job_id='other-job',room_id=other_room.id,name='Other item',quantity=1,unit_cuft=10)
    db.add(other);db.commit()
    with pytest.raises(HTTPException):save_inventory_edits(body(editor,update=[dict(id=other.id,fields={'quantity':8})]),access,db)
    db.rollback()
    assert other.quantity==1
