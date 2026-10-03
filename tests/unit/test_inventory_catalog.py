"""Shared catalog changes feed both customer inventory and moving-term selection."""
import importlib.util
import asyncio
import csv
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
import models
from manual_inventory import catalog, build_inventory, ManualInventoryInput


@pytest.fixture
def catalog_api():
    spec = importlib.util.spec_from_file_location('catalog_routes_test', BACKEND / 'routes/inventory_catalog.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'auth': SimpleNamespace(require_admin=lambda: None), 'database': SimpleNamespace(get_db=lambda: None)}):
        spec.loader.exec_module(module)
    engine = create_engine('sqlite://')
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield module, db
    engine.dispose()


def test_created_item_is_available_for_customer_inventory(catalog_api):
    api, db = catalog_api
    row = api.create_item(api.CatalogItemInput(name='  Massage   Chair ', cuft='45.25', weight='80'), None, db)
    assert row['name'] == 'Massage Chair' and row['active']
    assert row['id'] in [item['id'] for item in catalog(db)['items']]
    db.add(models.InventoryRoomType(id='room', name='Room', sort_order=0)); db.commit()
    body = ManualInventoryInput(request_id='00000000-0000-0000-0000-000000000001', rooms=[{'room_type_id':'room','name':'Living Room','items':[{'item_id':row['id'],'quantity':2}]}])
    rooms, rows, cuft, weight = build_inventory(body, db)
    assert cuft == 90.5
    assert weight == 160
    assert rows[0]['item_id'] == row['id']


def test_edit_keeps_item_id_and_inactive_preserves_record(catalog_api):
    api, db = catalog_api
    row = api.create_item(api.CatalogItemInput(name='Chair', cuft=20, weight=0), None, db)
    updated = api.update_item(row['id'], api.CatalogItemInput(name='Special Chair', cuft=30, weight=10, active=False), None, db)
    assert updated['id'] == row['id']
    assert updated['name'] == 'Special Chair'
    assert catalog(db)['items'] == []
    assert api.list_items(None, db)['items'] == [updated]
    assert db.get(models.InventoryCatalogItem, row['id']) is not None
    api.update_item(row['id'], api.CatalogItemInput(name='Special Chair', cuft=30, weight=10, active=True), None, db)
    assert len(catalog(db)['items']) == 1


@pytest.mark.parametrize('changes', [{'name':' '}, {'cuft':0}, {'cuft':-1}, {'cuft':'NaN'}, {'cuft':'1.234'}, {'weight':-1}, {'weight':'Infinity'}])
def test_bad_measurements_are_rejected(catalog_api, changes):
    api, _ = catalog_api
    with pytest.raises(ValueError):
        api.CatalogItemInput(**{**dict(name='Item',cuft=10,weight=0), **changes})


def test_update_missing_item_returns_404(catalog_api):
    api, db = catalog_api
    with pytest.raises(HTTPException) as error:
        api.update_item('missing', api.CatalogItemInput(name='Item', cuft=10, weight=0), None, db)
    assert error.value.status_code == 404


def test_material_lists_preserve_id_and_omitted_updates(catalog_api):
    api, db = catalog_api
    choices = [{'plan_id': 'book', 'material_id': 'cover', 'name': 'King cover', 'plan_name': 'Long distance'},
               {'plan_id': 'book', 'material_id': 'wrap', 'name': 'Plastic', 'plan_name': 'Long distance'}]
    materials = [{'plan_id': 'book', 'material_id': 'cover', 'quantity': 1, 'requirement': 'required'},
                 {'plan_id': 'book', 'material_id': 'wrap', 'quantity': 2, 'requirement': 'optional'}]
    with patch.object(api, 'material_options', return_value={'items': choices}):
        row = api.create_item(api.CatalogItemInput(name='Bed', cuft=80, weight=0, packing_materials=materials), None, db)
        assert len(row['packing_materials']) == 2
        assert upload_csv(api, db, api.export_items(None, db).body) == {'created': 0, 'updated': 1}
        assert api.list_items(None, db)['items'] == [row]
        updated = api.update_item(row['id'], api.CatalogItemInput(name='King bed', cuft=80, weight=0), None, db)
        assert updated['id'] == row['id']
        assert updated['packing_materials'] == row['packing_materials']
        with pytest.raises(HTTPException):
            api.update_item(row['id'], api.CatalogItemInput(name='Bed', cuft=80, weight=0, packing_materials=[materials[0], materials[0]]), None, db)
        cleared = api.update_item(row['id'], api.CatalogItemInput(name='Bed', cuft=80, weight=0, packing_materials=[]), None, db)
        assert cleared['packing_materials'] == []


def test_unknown_material_rejected(catalog_api):
    api, db = catalog_api
    with pytest.raises(HTTPException):
        api.create_item(api.CatalogItemInput(name='Bed', cuft=80, weight=0, packing_materials=[
            {'plan_id':'missing', 'material_id':'missing', 'quantity':1, 'requirement':'required'}]), None, db)


def upload_csv(api, db, content):
    return asyncio.run(api.import_items(UploadFile(filename='catalog.csv', file=io.BytesIO(content)), None, db))


@pytest.mark.parametrize('action', ['delete', 'deduplicate', 'migration'])
def test_removed_items_leave_no_packing_assignments(catalog_api, action):
    from catalog_material_cleanup import cleanup_missing_assignments
    from item_materials import material_setup
    api, db = catalog_api
    for id, size in [('keep', 30), ('remove', 20)]:
        db.add(models.InventoryCatalogItem(id=id, name='Chair', cuft=size, weight=10))
    config = {'rows': [{'item_id': id, 'material_id': 'cover', 'quantity': '1', 'requirement': 'required'} for id in ['keep', 'remove']],
              'defaults': [{'material_id': 'wrap', 'quantity': '1', 'requirement': 'optional'}],
              'protection_review': [{'item_id': 'remove', 'reason': 'Missing size'}], 'catalog_protection_v1': True}
    plan = models.PricingPlan(id='book', name='Book', company_name='Test', source_key='test', item_materials=json.dumps(config))
    db.add(plan)
    db.commit()
    if action == 'delete':
        api.delete_item('remove', None, db)
    elif action == 'deduplicate':
        api.deduplicate_items(None, db)
    else:
        db.get(models.InventoryCatalogItem, 'remove').deleted = True
        db.flush()
        assert len(material_setup(plan, db)['rows']) == 1
        cleanup_missing_assignments(db.connection())
        db.commit()
        db.refresh(plan)
    saved = json.loads(plan.item_materials)
    assert [row['item_id'] for row in saved['rows']] == ['keep']
    assert saved['protection_review'] == []
    assert saved['defaults'] == config['defaults']
    assert saved['catalog_protection_v1'] is True


def test_import_matches_names_and_volume_and_deduplicates_repeated_rows(catalog_api):
    api, db = catalog_api
    item = api.create_item(api.CatalogItemInput(name='Air Compressor / tank', cuft=20, weight=0, description='Keep this'), None, db)
    content = b'name,cuft,weight\nAir Compressor/Tank,20,140\nair compressor / tank,20,140\nAccordion,8,56\nACCORDION,8,56\nAccordion,10,70\n'
    assert upload_csv(api, db, content) == {'created': 2, 'updated': 1}
    assert upload_csv(api, db, content) == {'created': 0, 'updated': 3}
    assert len(api.list_items(None, db)['items']) == 3
    assert db.get(models.InventoryCatalogItem, item['id']).weight == 140
    assert db.get(models.InventoryCatalogItem, item['id']).description == 'Keep this'


def test_conflicting_duplicate_upload_does_not_save(catalog_api):
    api, db = catalog_api
    with pytest.raises(HTTPException, match='conflicting values'):
        upload_csv(api, db, b'name,cuft,weight\nChair,20,140\nCHAIR,20,150\n')
    assert api.list_items(None, db)['items'] == []


def test_manual_duplicate_add_and_rename_rejected(catalog_api):
    api, db = catalog_api
    api.create_item(api.CatalogItemInput(name='Air Compressor / tank', cuft=20, weight=0), None, db)
    duplicate = api.CatalogItemInput(name='AIR COMPRESSOR/tank', cuft=20, weight=10)
    with pytest.raises(HTTPException, match='already exists'):
        api.create_item(duplicate, None, db)
    other = api.create_item(api.CatalogItemInput(name='Chair', cuft=20, weight=0), None, db)
    with pytest.raises(HTTPException, match='already exists'):
        api.update_item(other['id'], duplicate, None, db)


def test_delete_hides_item_but_preserves_saved_inventory_reference(catalog_api):
    api, db = catalog_api
    item = api.create_item(api.CatalogItemInput(name='Chair', cuft=20, weight=10), None, db)
    db.add(models.InventoryRoomType(id='room', name='Room', sort_order=0))
    db.commit()
    api.delete_item(item['id'], None, db)
    assert api.list_items(None, db)['items'] == []
    assert catalog(db)['items'] == []
    assert 'Chair' not in api.export_items(None, db).body.decode('utf-8-sig')
    assert db.get(models.InventoryCatalogItem, item['id']) is not None
    body = ManualInventoryInput(request_id='00000000-0000-0000-0000-000000000001', rooms=[{'room_type_id':'room', 'name':'Room', 'items':[{'item_id':item['id'], 'quantity':1}]}])
    assert build_inventory(body, db)[2:] == (20, 10)
    with pytest.raises(HTTPException):
        api.update_item(item['id'], api.CatalogItemInput(name='Chair', cuft=20, weight=10), None, db)


def test_cleanup_keeps_largest_per_name_and_is_repeatable(catalog_api):
    api, db = catalog_api
    for item_id, name, cuft, weight, description in [('a', 'Air Compressor / tank', 20, 140, ''), ('b', 'Air Compressor/Tank', 30, 140, ''), ('c', 'Air Compressor/Tank', 40, 150, 'Largest'), ('d', 'Air Compressor/Tank', 40, 140, 'Special'), ('e', 'Chair', 10, 70, '')]:
        db.add(models.InventoryCatalogItem(id=item_id, name=name, cuft=cuft, weight=weight, description=description))
    db.commit()
    assert api.deduplicate_items(None, db) == {'removed': 3}
    assert api.deduplicate_items(None, db) == {'removed': 0}
    assert {item['id'] for item in api.list_items(None, db)['items']} == {'c', 'e'}
    retained = db.get(models.InventoryCatalogItem, 'c')
    assert retained.cuft == 40 and retained.weight == 150 and retained.description == 'Largest'
    assert db.get(models.InventoryCatalogItem, 'b').deleted


def test_cleanup_matches_missing_spaces_and_keeps_largest(catalog_api):
    api, db = catalog_api
    for item_id, name, cuft, weight in [('large', 'Artificial Plant', 12, 84), ('small', 'ArtificialPlant', 10, 70), ('other', 'Artificial Plant Stand', 5, 35)]:
        db.add(models.InventoryCatalogItem(id=item_id, name=name, cuft=cuft, weight=weight))
    db.commit()
    assert api.deduplicate_items(None, db) == {'removed': 1}
    assert {item['id'] for item in api.list_items(None, db)['items']} == {'large', 'other'}
    assert db.get(models.InventoryCatalogItem, 'small').deleted
    assert api.deduplicate_items(None, db) == {'removed': 0}


def test_import_matches_missing_spaces(catalog_api):
    api, db = catalog_api
    item = api.create_item(api.CatalogItemInput(name='Artificial Plant', cuft=12, weight=84), None, db)
    assert upload_csv(api, db, b'name,cuft,weight\nArtificialPlant,12,84\n') == {'created': 0, 'updated': 1}
    assert [row['id'] for row in api.list_items(None, db)['items']] == [item['id']]


def test_csv_round_trip_and_bulk_update(catalog_api):
    api, db = catalog_api
    row = api.create_item(api.CatalogItemInput(name='=Chair, special', description='Line one\nLine two', cuft='12.25', weight=4, active=False), None, db)
    exported = api.export_items(None, db)
    assert upload_csv(api, db, exported.body) == {'created': 0, 'updated': 1}
    assert api.list_items(None, db)['items'] == [row]
    rows = list(csv.DictReader(io.StringIO(exported.body.decode('utf-8-sig'))))
    rows[0]['weight'] = '25'
    rows.append({**rows[0], 'id': '', 'name': 'New chair', 'active': 'true'})
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=api.CSV_FIELDS)
    writer.writeheader(); writer.writerows(rows)
    assert upload_csv(api, db, output.getvalue().encode()) == {'created': 1, 'updated': 1}
    assert db.get(models.InventoryCatalogItem, row['id']).weight == 25
    assert len(api.list_items(None, db)['items']) == 2


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'cp1252', 'utf-16'])
def test_csv_spreadsheet_encodings_and_header_whitespace(catalog_api, encoding):
    api, db = catalog_api
    content = ' Name , CUFT ,weight\u00a0\r\nCaf\u00e9 chair,15,105\r\n'
    assert upload_csv(api, db, content.encode(encoding)) == {'created': 1, 'updated': 0}
    item = api.list_items(None, db)['items'][0]
    assert item['name'] == 'Caf\u00e9 chair'
    assert item['weight'] == 105


def test_csv_duplicate_normalized_headers_rejected(catalog_api):
    api, db = catalog_api
    with pytest.raises(HTTPException):
        upload_csv(api, db, b'name, Name ,cuft,weight\nA,B,1,1\n')
    assert api.list_items(None, db)['items'] == []


def test_csv_hidden_markers_are_removed_without_losing_unicode(catalog_api):
    api, db = catalog_api
    content = '\ufeffName\u200b,cuft,\u2060weight\n\u200bCafé\u00a0 chair\ufeff,15,105\n'
    assert upload_csv(api, db, content.encode('utf-8')) == {'created': 1, 'updated': 0}
    assert api.list_items(None, db)['items'][0]['name'] == 'Café chair'


@pytest.mark.parametrize('bad_row', ['missing,Bad,5,1', ',Bad,-1,1', ',Bad,5,1,extra'])
def test_csv_invalid_row_does_not_save_partial_changes(catalog_api, bad_row):
    api, db = catalog_api
    row = api.create_item(api.CatalogItemInput(name='Original', cuft=10, weight=1), None, db)
    content = f"id,name,cuft,weight\n{row['id']},Changed,20,2\n{bad_row}\n"
    with pytest.raises(HTTPException) as error:
        upload_csv(api, db, content.encode())
    assert error.value.status_code == 422
    assert api.list_items(None, db)['items'] == [row]


@pytest.mark.parametrize('content', [b'', b'name,cuft,weight\n', b'name,name,cuft,weight\nA,B,1,1', b'wrong\nvalue', b'\xff'])
def test_csv_bad_files_rejected(catalog_api, content):
    api, db = catalog_api
    with pytest.raises(HTTPException) as error:
        upload_csv(api, db, content)
    assert error.value.status_code == 422


def test_csv_duplicate_ids_rejected_and_omitted_items_kept(catalog_api):
    api, db = catalog_api
    row = api.create_item(api.CatalogItemInput(name='Chair', description='Keep me', cuft=10, weight=1, active=False), None, db)
    line = f"{row['id']},Updated,20,2\n"
    with pytest.raises(HTTPException, match='duplicate item ID'):
        upload_csv(api, db, ('id,name,cuft,weight\n' + line + line).encode())
    upload_csv(api, db, ('id,name,cuft,weight\n' + line).encode())
    updated = db.get(models.InventoryCatalogItem, row['id'])
    assert updated.description == 'Keep me' and updated.active is False
    upload_csv(api, db, b'name,cuft,weight\nNew,5,1\n')
    assert len(api.list_items(None, db)['items']) == 2
