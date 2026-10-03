import sys
from pathlib import Path
from decimal import Decimal

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from item_materials import sized_optional_defaults
from long_distance_packing import MaterialRate


@pytest.mark.parametrize('volume,expected', [(20, {'cm','ws'}),(25, {'cl','ws'}),(26, {'cl','wl'}),(100, {'cx','wl'}),(501,set()),(None,set())])
def test_optional_sizes_choose_one_fitting_size_per_family(volume, expected):
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
