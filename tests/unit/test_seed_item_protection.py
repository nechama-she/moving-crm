import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from long_distance_packing import MaterialRate, PACKING_CARD_PREFIX
from seed_item_protection import protection_assignment, seed_item_protection, VERSION
from models import Base, PricingPlan, PricingService, InventoryCatalogItem


def materials():
    specs = [('twin', 'Mattress Bag (twin)', None, 'twin'), ('queen', 'Mattress Bag (Queen)', None, 'queen'),
             ('sofa', 'Sofa cover', None, None), ('mirror', 'Mirror Box: 6 cuft', 6, None),
             ('mirror-xl', 'Mirror Box: 7 cuft and up', 30, None),
             ('picture', 'Picture Box Standard 3.0cf: 3 CU', 3, None),
             ('crate', 'Carton Crate Medium', 24, None), ('crate-lg', 'Carton Crate Large', 90, None)]
    return [MaterialRate(id=id, name=name, material_price=26, packing_price=12, unpacking_price=15,
                         capacity=capacity, capacity_unit='mattress_size' if size else 'cuft', mattress_size=size)
            for id, name, capacity, size in specs]


@pytest.mark.parametrize('name,volume,material,quantity,requirement', [
    ('Mattress Queen', 35, 'queen', '1', 'required'),
    ('Box Spring Twin', 20, 'twin', '1', 'required'),
    ('Sofa', 65, 'sofa', '1', 'optional'),
    ('Fabric sectional 3-piece', 120, 'sofa', '3', 'optional'),
    ('Sectional sofa per seating', 45, 'sofa', '1', 'optional'),
    ('Mirror Small', 5, 'mirror', '1', 'required'),
    ('Mirror Large', 15, 'mirror-xl', '1', 'required'),
    ('Picture Small', 2, 'picture', '1', 'required'),
    ('End Table Marble Top', 6, 'crate', '1', 'required'),
    ('Glass Conference Table', 80, 'crate-lg', '1', 'required'),
])
def test_assignments(name, volume, material, quantity, requirement):
    rows, reason = protection_assignment(SimpleNamespace(id='item', name=name, cuft=volume), materials())
    assert reason is None
    assert rows == [dict(item_id='item', material_id=material, quantity=quantity, requirement=requirement)]


@pytest.mark.parametrize('name', ['Leather Sofa', 'Sofa Table', 'Picture Box', 'Glass Vase'])
def test_unrelated_items_not_assigned(name):
    assert protection_assignment(SimpleNamespace(id='item', name=name, cuft=10), materials()) == ([], None)


@pytest.mark.parametrize('name', ['Mattress California King', 'Box Spring King/Split', 'Mattress Crib', 'Mattress', 'Dresser With Mirror'])
def test_unknown_size_requires_review(name):
    rows, reason = protection_assignment(SimpleNamespace(id='item', name=name, cuft=40), materials())
    assert not rows and reason


def test_pipeline_seed_corrects_existing_and_runs_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(PricingPlan.__table__.insert().values(id='book', company_name='Test', name='Book', source_key='test', item_materials=json.dumps({'rows':[{'item_id':'custom','material_id':'sofa','quantity':'2','requirement':'required'}],'defaults':[]})))
        connection.execute(PricingService.__table__.insert().values(id='service', plan_id='book', name='Packing', comments=PACKING_CARD_PREFIX+json.dumps({'materials':[m.model_dump(mode='json') for m in materials()]})))
        for id, name in [('custom','Sofa'),('new','Mattress Queen'),('review','Mattress Crib')]:
            connection.execute(InventoryCatalogItem.__table__.insert().values(id=id, name=name, cuft=35, weight=100))
        seed_item_protection(connection)
        saved = connection.execute(select(PricingPlan.item_materials)).scalar_one()
        data = json.loads(saved)
        assert data[VERSION]
        assert len(data['rows']) == 2
        sofa = next(row for row in data['rows'] if row['item_id'] == 'custom')
        assert sofa['quantity'] == '1' and sofa['requirement'] == 'optional'
        assert next(row for row in data['rows'] if row['item_id'] == 'new')['material_id'] == 'queen'
        assert data['protection_review'][0]['item_id'] == 'review'
        seed_item_protection(connection)
        assert connection.execute(select(PricingPlan.item_materials)).scalar_one() == saved
