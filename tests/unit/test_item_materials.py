import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from item_materials import ItemMaterialsInput, material_setup, save_material_assignments, customer_item_materials
from long_distance_packing import PACKING_CARD_PREFIX


def setup():
    db = Mock()
    db.query.return_value.filter_by.return_value = db.query.return_value
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


def test_customer_required_and_optional_materials_use_catalog_and_quantity():
    plan, db = setup()
    db.query.return_value.all.return_value = [SimpleNamespace(id='bed',name='King bed')]
    card = json.loads(plan.services[0].comments[len(PACKING_CARD_PREFIX):])
    card['materials'].append(dict(id='wrap',name='Bed wrap',material_price=18,packing_price=12,unpacking_price=0))
    plan.services[0].comments = PACKING_CARD_PREFIX + json.dumps(card)
    plan.item_materials=json.dumps([
        dict(item_id='bed',material_id='cover',quantity=1,requirement='required'),
        dict(item_id='bed',material_id='wrap',quantity=2,requirement='optional')])
    inventory=[dict(name='Bed King',room='Bedroom',amount=2)]
    rows, matched=customer_item_materials(plan,inventory,db)
    assert len(rows)==4 and len({row['id'] for row in rows})==4
    assert rows[0]['requirement']=='required' and rows[0]['material_name']=='King cover'
    assert rows[0]['labor_price']==12 and rows[0]['price']==38
    assert rows[1]['requirement']=='optional' and rows[1]['price']==60
    assert rows[1]['labor_price']==24 and rows[1]['material_price']==36
    assert 'bed king' in matched
    assert customer_item_materials(plan,inventory,db)[0]==rows
    assert inventory==[dict(name='Bed King',room='Bedroom',amount=2)]


def test_configured_customer_price_charges_only_selected_material():
    import ast
    from decimal import Decimal
    source=(Path(__file__).resolve().parents[2]/'backend/routes/pricing.py').read_text(encoding='utf-8')
    function=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='customer_package_lines')
    namespace={'Decimal':Decimal}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'pricing.py','exec'),namespace)
    package={'rates':{},'items':[
        dict(id='cover',label='Bed King',quantity=1,material_name='King cover',price=38,labor_price=12,material_price=26),
        dict(id='wrap',label='Bed King',quantity=1,material_name='Wrap',price=30,labor_price=12,material_price=18)]}
    lines=namespace['customer_package_lines'](package,dict(mode='none',item_ids=['cover'],material_item_ids=['cover']))
    assert len(lines)==1 and lines[0]['amount']==38
    assert 'King cover' in lines[0]['description']
    lines=namespace['customer_package_lines'](package,dict(mode='none',item_ids=['cover','wrap'],material_item_ids=['cover']))
    assert sum(line['amount'] for line in lines)==50


def test_configured_materials_do_not_require_fabric_question():
    from estimate_questions import unanswered_questions
    assert unanswered_questions({'packing_package':{'configured_materials':True,'selection':{'mode':'none','has_additional_protection':False}}})==[]


def test_default_material_applies_only_without_item_specific_materials():
    plan, db = setup()
    db.query.return_value.all.return_value = [SimpleNamespace(id='bed', name='King bed')]
    card = json.loads(plan.services[0].comments[len(PACKING_CARD_PREFIX):])
    card['materials'].append(dict(id='wrap',name='Default wrap',material_price=10,packing_price=5,unpacking_price=0))
    plan.services[0].comments = PACKING_CARD_PREFIX + json.dumps(card)
    body = ItemMaterialsInput(
        rows=[dict(item_id='bed',material_id='cover',requirement='required',quantity=1)],
        defaults=[dict(material_id='wrap',requirement='optional',quantity=2)],
    )
    saved = save_material_assignments(plan, body, db)
    assert saved['defaults'][0]['material_id'] == 'wrap'
    rows, _ = customer_item_materials(plan, [
        dict(item_id='bed',name='King bed',room='Bedroom',amount=1),
        dict(name='Dresser',room='Bedroom',amount=1),
    ], db)
    assert [(row['label'], row['material_name'], row['requirement']) for row in rows] == [
        ('King bed', 'King cover', 'required'),
        ('Dresser', 'Default wrap', 'optional'),
    ]


def test_multiple_default_materials_have_separate_choices_in_one_item_group():
    plan, db = setup()
    db.query.return_value.all.return_value = [SimpleNamespace(id='tv', name='TV')]
    card = json.loads(plan.services[0].comments[len(PACKING_CARD_PREFIX):])
    card['materials'].append(dict(id='wrap', name='Shrink Wrap', material_price=10, packing_price=5, unpacking_price=0))
    plan.services[0].comments = PACKING_CARD_PREFIX + json.dumps(card)
    save_material_assignments(plan, ItemMaterialsInput(rows=[], defaults=[
        dict(material_id='cover', requirement='optional', quantity=1),
        dict(material_id='wrap', requirement='optional', quantity=1),
    ]), db)

    rows, _ = customer_item_materials(plan, [dict(item_id='tv', name='TV', room='Living Room', amount=1)], db)

    assert len(rows) == 2
    assert [row['label'] for row in rows] == ['TV', 'TV']
    assert len({row['group_id'] for row in rows}) == 1
    assert len({row['id'] for row in rows}) == 2
    assert [row['material_name'] for row in rows] == ['King cover', 'Shrink Wrap']
    assert [(row['labor_price'], row['material_price']) for row in rows] == [(12, 26), (5, 10)]


def test_defaults_do_not_apply_to_boxes_but_explicit_box_materials_do():
    plan, db = setup()
    db.query.return_value.all.return_value = [
        SimpleNamespace(id='small-box', name='Small Box (CP)', active=True),
        SimpleNamespace(id='vase', name='Vase', active=True),
    ]
    db.query.return_value.order_by.return_value.all.return_value = db.query.return_value.all.return_value
    save_material_assignments(plan, ItemMaterialsInput(rows=[], defaults=[
        dict(material_id='cover', requirement='optional', quantity=1),
    ]), db)
    inventory = [
        dict(item_id='small-box', name='Small Box (CP)', room='Office', amount=2),
        dict(item_id='medium-box', name='Medium Box (CP)', room='Office', amount=1),
        dict(item_id='vase', name='Vase', room='Office', amount=1),
    ]

    rows, _ = customer_item_materials(plan, inventory, db)

    assert [row['label'] for row in rows] == ['Vase']

    save_material_assignments(plan, ItemMaterialsInput(rows=[
        dict(item_id='small-box', material_id='cover', requirement='optional', quantity=1),
    ], defaults=[dict(material_id='cover', requirement='optional', quantity=1)]), db)
    rows, _ = customer_item_materials(plan, inventory, db)
    assert [row['label'] for row in rows] == ['Small Box (CP) (1)', 'Small Box (CP) (2)', 'Vase']
