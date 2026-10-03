import sys
from pathlib import Path
from decimal import Decimal

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from item_materials import sized_optional_defaults
from long_distance_packing import MaterialRate


@pytest.mark.parametrize('volume,expected', [(20, {'cm','ws'}),(25, {'cl','ws'}),(26, {'cl','wl'}),(100, {'cx','wl'}),(501,set()),(None,set())])
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


@pytest.mark.parametrize('inventory_id', ['deleted-tv', 'custom-tv', 'current-tv'])
def test_required_tv_box_wins_over_optional_defaults(inventory_id):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from item_materials import customer_item_materials
    name = 'TV Flat Screen - 33 - 59'
    db = Mock()
    db.query.return_value.all.return_value = [
        SimpleNamespace(id='deleted-tv',name=name,cuft=10,deleted=True),
        SimpleNamespace(id='current-tv',name=name,cuft=15,deleted=False)]
    plan = SimpleNamespace(id='book',item_materials=json.dumps({
        'rows':[dict(item_id='current-tv',material_id='tv-box',requirement='required',quantity='1')],
        'defaults':[dict(material_id='crate',requirement='optional',quantity='1')]}),
        services=[SimpleNamespace(comments='__ld_packing__:'+json.dumps({'materials':[
            dict(id=id,name=label,material_price=10,packing_price=5,unpacking_price=0)
            for id,label in [('tv-box','TV Box up to 59 inches'),('crate','Carton Crate Large')]]}))])
    rows,_ = customer_item_materials(plan,[dict(item_id=inventory_id,name=name,cuft=10,quantity=1)],db)
    assert len(rows) == 1
    assert rows[0]['requirement'] == 'required'
    assert rows[0]['material_name'] == 'TV Box up to 59 inches'


def test_wizard_questions_use_current_name_and_per_item_volume():
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from item_materials import customer_item_materials
    materials = [dict(id=id,name=id,material_price=10,packing_price=5,unpacking_price=0,
                      rule={'measure':'cubic_feet',**limits}) for id,limits in [
                          ('small',{'maximum':25}),('big',{'minimum':25,'minimum_inclusive':False})]]
    plan = SimpleNamespace(id='book', item_materials=json.dumps({'rows':[], 'defaults':[
        {'material_id':id,'requirement':'optional','quantity':'1'} for id in ['small','big']]}),
        services=[SimpleNamespace(comments='__ld_packing__:'+json.dumps({'materials':materials}))])
    db = Mock()
    db.query.return_value.all.return_value = [SimpleNamespace(id='sofa',name='L Shaped Sofa - 2 Piece',cuft=100,deleted=False)]
    rows,_ = customer_item_materials(plan,[{'item_id':'custom-old','name':'L Shaped Sofa','amount':2,'cuft':200,'unit_cuft':100,'room':'Dining Room'}],db)
    assert len(rows) == 2
    assert all(row['material_name']=='big' for row in rows)
    assert all(row['label'].startswith('L Shaped Sofa - 2 Piece') for row in rows)


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
    assert len(rows)==(10 if explicit else 4)
    assert {row['materials'][0]['id'] for row in rows} == ({'small','large','xl','under','over'} if explicit else {'large','over'})


@pytest.mark.parametrize('kind', ['up_to', 'over'])
@pytest.mark.parametrize('volume,expected', [(25, {'large', 'under'}), (50, {'large', 'over'}), (90, {'large', 'over'}), (91, {'xl', 'over'}), (501, set())])
def test_breakfront_and_armchair_default_sizes(kind, volume, expected):
    specs = [('medium', 'Carton Crate Medium', 24, 'up_to'),
             ('large', 'Carton Crate Large', 90, 'up_to'),
             ('xl', 'Carton Crate Extra Large', 500, 'up_to'),
             ('under', 'Shrink Wrap (per item) under 25 cubic foot', 25, 'up_to'),
             ('over', 'Shrink Wrap (per item) Over 25 cubic foot', 500, kind)]
    rates = {id: MaterialRate(id=id, name=name, capacity=capacity, capacity_kind=capacity_kind,
                             material_price=10, packing_price=5, unpacking_price=0)
             for id, name, capacity, capacity_kind in specs}
    defaults = [dict(material_id=id, requirement='optional', quantity='1') for id in rates]
    assert {row['material_id'] for row in sized_optional_defaults(defaults, rates, Decimal(volume))} == expected
