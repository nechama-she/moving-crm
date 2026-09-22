"""Shared catalog changes feed both customer inventory and moving-term selection."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
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
