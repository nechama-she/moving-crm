import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from item_materials import ItemMaterialsInput, material_setup, save_material_assignments
from long_distance_packing import PACKING_CARD_PREFIX


def setup():
    db = Mock()
    db.query.return_value.order_by.return_value.all.return_value = [SimpleNamespace(id='bed', name='King bed', active=True)]
    card = {'materials':[{'id':'cover','name':'King cover','material_price':26,'packing_price':12,'unpacking_price':0}]}
    plan = SimpleNamespace(id='east', item_materials=None, services=[SimpleNamespace(comments=PACKING_CARD_PREFIX+json.dumps(card))])
    return plan, db


def test_book_setup_starts_empty_and_saves_only_this_book():
    plan, db = setup()
    other = SimpleNamespace(item_materials=None)
    assert material_setup(plan, db)['rows'] == []
    body = ItemMaterialsInput(rows=[dict(item_id='bed',material_id='cover',requirement='required',quantity=1)])
    result = save_material_assignments(plan, body, db)
    assert result['rows'][0]['requirement'] == 'required'
    assert plan.id == 'east' and other.item_materials is None
    assert db.commit.call_count == 1
    assert result['materials'] == [{'id':'cover','name':'King cover'}]


def test_material_from_other_book_is_rejected():
    plan, db = setup()
    with pytest.raises(HTTPException):
        save_material_assignments(plan, ItemMaterialsInput(rows=[dict(item_id='bed',material_id='foreign',requirement='optional',quantity=1)]), db)
    db.commit.assert_not_called()
    assert plan.item_materials is None


def test_duplicates_and_invalid_quantity_rejected():
    row = dict(item_id='bed', material_id='cover', requirement='required', quantity=1)
    with pytest.raises(ValueError):
        ItemMaterialsInput(rows=[row,row])
    with pytest.raises(ValueError):
        ItemMaterialsInput(rows=[{**row,'quantity':0}])


def test_edit_and_explicit_removal_keep_plan_id():
    plan, db = setup()
    row = dict(item_id='bed',material_id='cover',requirement='required',quantity=1)
    save_material_assignments(plan, ItemMaterialsInput(rows=[row]), db)
    result = save_material_assignments(plan, ItemMaterialsInput(rows=[{**row,'requirement':'optional','quantity':2}]), db)
    assert result['rows'][0]['quantity'] == '2'
    assert result['rows'][0]['requirement'] == 'optional'
    assert save_material_assignments(plan, ItemMaterialsInput(rows=[]), db)['rows'] == []
    assert plan.id == 'east'
