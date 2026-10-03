import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from item_materials import customer_item_materials, material_setup, ItemMaterialsInput, save_material_assignments
from migrate_default_material_copies import VERSION, clean_default_copies, cleanup_default_material_copies


def configuration():
    defaults = [dict(material_id=id, requirement='optional', quantity='1')
                for id in ('wrap-under', 'wrap-over', 'crate-medium', 'crate-large', 'crate-xl')]
    return {
        'item_material_sizes_v3': True,
        'defaults': defaults,
        'rows': [dict(row, item_id=item) for item in ('chair', 'cabinet') for row in defaults] + [
            dict(item_id='sofa', material_id='cover', requirement='optional', quantity='4'),
            dict(item_id='tv', material_id='tv-box', requirement='required', quantity='1'),
            dict(item_id='glass', material_id='crate-large', requirement='required', quantity='2'),
        ],
        'protection_review': [{'item_id': 'mirror', 'reason': 'Confirm dimensions'}],
    }


@pytest.mark.parametrize('version', [1, 2, 3])
def test_cleanup_keeps_specific_materials_defaults_and_backup(version):
    saved = configuration()
    del saved['item_material_sizes_v3']
    saved[f'item_material_sizes_v{version}'] = True
    original = copy.deepcopy(saved)
    cleaned = clean_default_copies(saved)
    assert cleaned['rows'] == saved['rows'][10:]
    assert cleaned['defaults'] == saved['defaults']
    assert cleaned['protection_review'] == saved['protection_review']
    assert cleaned[VERSION]['removed_rows'] == saved['rows'][:10]
    assert saved == original
    assert clean_default_copies(cleaned) == cleaned


def test_preserves_partial_bundles_custom_quantities_and_unaffected_books():
    saved = configuration()
    saved['rows'][0]['quantity'] = '2'
    saved['rows'].pop(5)
    assert clean_default_copies(saved)['rows'] == saved['rows']
    del saved['item_material_sizes_v3']
    assert clean_default_copies(saved) == saved
    assert clean_default_copies(saved['rows']) == saved['rows']


@pytest.mark.parametrize('count', [0, 1, 2, 3, 4])
def test_never_removes_an_item_with_fewer_than_all_five_defaults(count):
    saved = configuration()
    saved['rows'] = [dict(row, item_id='chair') for row in saved['defaults'][:count]]
    assert clean_default_copies(saved)['rows'] == saved['rows']
    # Even when the book itself has fewer defaults, don't clear smaller bundles.
    saved['defaults'] = saved['defaults'][:count]
    assert clean_default_copies(saved) == saved


@pytest.mark.parametrize('index', range(5))
@pytest.mark.parametrize('change', [{'quantity': '2'}, {'requirement': 'required'}, {'material_id': 'custom'}])
def test_each_of_the_five_defaults_must_match(index, change):
    saved = configuration()
    saved['rows'] = [dict(row, item_id='chair') for row in saved['defaults']]
    saved['rows'][index].update(change)
    assert clean_default_copies(saved)['rows'] == saved['rows']


def test_cleanup_keeps_extra_assignments_and_compares_numeric_quantities():
    saved = configuration()
    saved['rows'][0]['quantity'] = 1.0
    custom = dict(item_id='chair', material_id='cover', requirement='optional', quantity=2)
    saved['rows'].append(custom)
    cleaned = clean_default_copies(saved)
    assert cleaned['rows'] == saved['rows'][10:]
    assert custom in cleaned['rows']


def test_screenshot_bundles_removed_but_specific_boxes_and_mattress_bags_remain():
    saved = configuration()
    materials = [SimpleNamespace(id=id, name=name) for id, name in [
        ('wrap-under', 'Shrink Wrap (per item) under 25 cubic foot'),
        ('wrap-over', 'Shrink Wrap (per item) Over 25 cubic foot'),
        ('crate-small', 'Carton Crate Small'), ('crate-medium', 'Carton Crate Medium'),
        ('crate-large', 'Carton Crate Large'), ('crate-xl', 'Carton Crate Extra Large')]]
    specific = [
        dict(item_id='air-mattress', material_id='extra-large-box', requirement='optional', quantity='1'),
        dict(item_id='bunk-bed', material_id='twin-bag', requirement='required', quantity='2'),
        dict(item_id='bed-bunks', material_id='twin-bag', requirement='required', quantity='2'),
        dict(item_id='fragile-item', material_id='crate-medium', requirement='required', quantity='1'),
        dict(item_id='custom-small-crate', material_id='crate-small', requirement='optional', quantity='1'),
    ]
    for item in ('accordion', 'air-conditioner'):
        saved['rows'].extend(dict(row, item_id=item, material_id=(
            'crate-small' if row['material_id'] == 'crate-large' else row['material_id']))
            for row in saved['defaults'])
    saved['rows'].extend(specific)
    cleaned = clean_default_copies(saved, materials)
    assert cleaned['rows'] == configuration()['rows'][10:] + specific
    assert len(cleaned[VERSION]['removed_rows']) == 20
    assert cleaned['defaults'] == saved['defaults']
    # A changed quantity makes this an override rather than a copied bundle.
    saved['rows'][13]['quantity'] = '2'
    cleaned = clean_default_copies(saved, materials)
    assert len([row for row in cleaned['rows'] if row['item_id'] == 'accordion']) == 5


def test_database_cleanup_is_once_per_book_and_retains_later_edits():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE pricing_plans (id TEXT PRIMARY KEY, item_materials TEXT, updated_at TIMESTAMP)'))
        connection.execute(text('CREATE TABLE pricing_services (plan_id TEXT, comments TEXT)'))
        for id, config in [('affected', configuration()), ('untouched', {'rows': [], 'defaults': []})]:
            connection.execute(text('INSERT INTO pricing_plans (id, item_materials) VALUES (:id, :config)'), {'id': id, 'config': json.dumps(config)})
        assert cleanup_default_material_copies(connection) == 10
        raw = connection.execute(text("SELECT item_materials FROM pricing_plans WHERE id='affected'")).scalar_one()
        saved = json.loads(raw)
        saved['rows'].extend(saved[VERSION]['removed_rows'])
        connection.execute(text("UPDATE pricing_plans SET item_materials=:config WHERE id='affected'"), {'config': json.dumps(saved)})
        assert cleanup_default_material_copies(connection) == 0
        assert json.loads(connection.execute(text("SELECT item_materials FROM pricing_plans WHERE id='affected'")).scalar_one()) == saved
    engine.dispose()


def test_cleaned_chair_uses_filtered_global_defaults_without_resaving_copies():
    saved = clean_default_copies(configuration())
    materials = [dict(id=row['material_id'], name=row['material_id'], material_price=10,
                      packing_price=5, unpacking_price=0, capacity=capacity, capacity_kind=kind)
                 for row, capacity, kind in zip(saved['defaults'], [25, 25, 24, 90, 500],
                                                ['up_to', 'over', 'up_to', 'up_to', 'up_to'])]
    plan = SimpleNamespace(id='book', item_materials=json.dumps(saved), services=[
        SimpleNamespace(comments='__ld_packing__:' + json.dumps({'materials': materials}))])
    db = Mock()
    catalog = [SimpleNamespace(id=id, name=id, cuft=20, active=True, deleted=False)
               for id in ('chair', 'cabinet', 'sofa', 'tv', 'glass')]
    db.query.return_value.all.return_value = catalog
    db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = catalog
    setup = material_setup(plan, db)
    assert not any(row['item_id'] == 'chair' for row in setup['rows'])
    rows, _ = customer_item_materials(plan, [dict(item_id='chair', name='chair', amount=1)], db)
    assert {row['materials'][0]['id'] for row in rows} == {'wrap-under', 'crate-medium', 'crate-large', 'crate-xl'}
    result = save_material_assignments(plan, ItemMaterialsInput(rows=setup['rows'], defaults=setup['defaults']), db)
    assert result['rows'] == setup['rows']
    assert json.loads(plan.item_materials)[VERSION] == saved[VERSION]
