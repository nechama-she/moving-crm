import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from long_distance_packing import MaterialRate, PACKING_CARD_PREFIX
from migrate_item_material_sizes import fit_material, migrate_item_material_sizes, VERSION
from models import Base, InventoryCatalogItem, PricingPlan, PricingService


def materials():
    return [MaterialRate(id=id, name=name, capacity=capacity, capacity_unit='cuft', material_price=10, packing_price=5, unpacking_price=0)
            for id, name, capacity in [('cm','Carton Crate Medium',24),('cl','Carton Crate Large',90),('cx','Carton Crate Extra Large',500),('ws','Shrink Wrap under 25',25),('wl','Shrink Wrap over 25',500)]]


@pytest.mark.parametrize('source,volume,expected', [('cl',24,'cm'),('cm',25,'cl'),('cm',90,'cl'),('cl',91,'cx'),('cx',501,None),('wl',25,'ws'),('ws',26,'wl')])
def test_capacity_boundaries(source, volume, expected):
    rates = materials()
    result = fit_material(next(m for m in rates if m.id == source), rates, volume)
    assert (result.id if result else None) == expected


def test_saved_assignments_defaults_and_repeat_pipeline():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        config = {'catalog_protection_v1':True,'rows':[{'item_id':'large','material_id':'cm','quantity':'2','requirement':'required'}],
                  'defaults':[{'material_id':'wl','quantity':'1','requirement':'optional'},{'material_id':'cl','quantity':'1','requirement':'optional'}]}
        connection.execute(PricingPlan.__table__.insert().values(id='book',company_name='Test',name='Book',source_key='test',item_materials=json.dumps(config)))
        connection.execute(PricingService.__table__.insert().values(id='svc',plan_id='book',name='Packing',comments=PACKING_CARD_PREFIX+json.dumps({'materials':[m.model_dump(mode='json') for m in materials()]})))
        for id, volume in [('small',10),('large',100)]:
            connection.execute(InventoryCatalogItem.__table__.insert().values(id=id,name='Chair '+id,cuft=volume,weight=70))
        migrate_item_material_sizes(connection)
        raw = connection.execute(select(PricingPlan.item_materials)).scalar_one()
        saved = json.loads(raw)
        assert saved[VERSION] and saved['catalog_protection_v1']
        assert saved['defaults'] == config['defaults']
        assert saved['rows'][0] == {'item_id':'large','material_id':'cx','quantity':'2','requirement':'required'}
        assert {r['material_id'] for r in saved['rows'] if r['item_id']=='small'} == {'ws','cm'}
        assert all(r['requirement']=='optional' for r in saved['rows'] if r['item_id']=='small')
        migrate_item_material_sizes(connection)
        assert connection.execute(select(PricingPlan.item_materials)).scalar_one() == raw
