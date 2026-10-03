import sys
from pathlib import Path
from decimal import Decimal

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from item_materials import sized_optional_defaults
from long_distance_packing import MaterialRate


@pytest.mark.parametrize('volume,expected', [(20, {'cm','cl','cx','ws','wl'}),(25, {'cl','cx','ws','wl'}),(26, {'cl','cx','wl'}),(100, {'cx','wl'}),(501,set()),(None,set())])
def test_optional_sizes_respect_each_configured_limit(volume, expected):
    specs = [('cm','Carton Crate Medium',24),('cl','Carton Crate Large',90),('cx','Carton Crate Extra Large',500),('ws','Shrink Wrap small',25),('wl','Shrink Wrap large',500)]
    rates = {id:MaterialRate(id=id,name=name,capacity=capacity,material_price=10,packing_price=5,unpacking_price=0) for id,name,capacity in specs}
    defaults = [{'material_id':id,'requirement':'optional','quantity':'1'} for id in rates]
    result = sized_optional_defaults(defaults,rates,Decimal(volume) if volume is not None else None)
    assert {row['material_id'] for row in result} == expected
    assert len(defaults) == 5


@pytest.mark.parametrize('kind,volume,shown', [('up_to',60,True),('up_to',70,False),('over',60,False),('over',70,True)])
def test_any_material_name_uses_its_size_limit(kind, volume, shown):
    rate = MaterialRate(id='custom',name='Custom protective material',capacity=60,capacity_kind=kind,material_price=10,packing_price=5,unpacking_price=0)
    defaults = [{'material_id':'custom','requirement':'optional','quantity':'1'}]
    assert bool(sized_optional_defaults(defaults,{'custom':rate},Decimal(volume))) is shown


def test_required_defaults_are_not_filtered():
    rate = MaterialRate(id='crate',name='Carton Crate',capacity=24,material_price=10,packing_price=5,unpacking_price=0)
    defaults = [{'material_id':'crate','requirement':'required','quantity':'2'}]
    assert sized_optional_defaults(defaults,{'crate':rate},Decimal(50)) == defaults


@pytest.mark.parametrize('volume,expected', [(20,{'under','crate'}),(25,{'under','crate'}),(30,{'over','crate'}),(70,{'over'})])
def test_legacy_rule_limits_filter_defaults(volume, expected):
    rates = {}
    for id, limits in [('under',{'maximum':25}),('over',{'minimum':25,'minimum_inclusive':False}),('crate',{'maximum':60})]:
        rates[id] = MaterialRate(id=id,name=id,material_price=10,packing_price=5,unpacking_price=0,
                                 rule={'measure':'cubic_feet',**limits})
    defaults = [{'material_id':id,'requirement':'optional','quantity':'1'} for id in rates]
    assert {row['material_id'] for row in sized_optional_defaults(defaults,rates,Decimal(volume))} == expected


@pytest.mark.parametrize('explicit', [True, False])
def test_inventory_filters_saved_item_options_and_defaults(explicit):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from item_materials import customer_item_materials
    specs = [('small','Carton Crate Medium',24),('large','Carton Crate Large',90),('xl','Carton Crate Extra Large',500),('under','Shrink Wrap under 25',25),('over','Shrink Wrap over 25',500)]
    materials = [dict(id=id,name=name,capacity=capacity,material_price=10,packing_price=5,unpacking_price=0) for id,name,capacity in specs]
    choices = [dict(material_id=id,requirement='optional',quantity='1',**({'item_id':'chair'} if explicit else {})) for id,_,_ in specs]
    plan = SimpleNamespace(id='book', item_materials=json.dumps({'rows':choices if explicit else [],'defaults':[] if explicit else choices}), services=[SimpleNamespace(comments='__ld_packing__:'+json.dumps({'materials':materials}))])
    db = Mock()
    db.query.return_value.all.return_value = [SimpleNamespace(id='chair',name='Accent Chair',cuft=30,deleted=False)]
    rows,_ = customer_item_materials(plan,[dict(item_id='chair',name='Accent Chair',amount=2,cuft=60)],db)
    assert len(rows)==(10 if explicit else 6)
    assert {row['materials'][0]['id'] for row in rows} == ({'small','large','xl','under','over'} if explicit else {'large','xl','over'})
