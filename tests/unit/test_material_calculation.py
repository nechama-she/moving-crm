import sys
from pathlib import Path
from decimal import Decimal
import pytest
from pydantic import ValidationError
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'backend'))
from material_calculation import MaterialItem, calculate_materials
from long_distance_packing import MaterialRate, MaterialRule


def rate(id='wrap', material=10, labor=12, **rule):
    return MaterialRate(id=id,name=id,material_price=material,packing_price=labor,unpacking_price=15,rule=MaterialRule(**rule))


@pytest.mark.parametrize('size,expected', [(24,22),(25,22),(26,30)])
def test_wrap_boundaries(size,expected):
    materials=[rate(measure='cubic_feet',maximum=25),rate('large',material=18,measure='cubic_feet',minimum=25,minimum_inclusive=False)]
    result=calculate_materials(materials,MaterialItem(protection='fabric',cubic_feet=size,quantity=3))
    assert result['packing_only']==36
    assert result['packing_and_material']==expected*3


def test_specific_over_generic_and_unknown_size():
    materials=[rate(),rate('tv-small',protection='fragile',item_type='tv',measure='screen_inches',maximum=61),rate('tv-large',protection='fragile',item_type='tv',measure='screen_inches',minimum=61,minimum_inclusive=False)]
    for size,identifier in [(61,'tv-small'),(62,'tv-large')]:
        result=calculate_materials(materials,MaterialItem(protection='fragile',item_type='tv',screen_inches=size))
        assert result['lines'][0]['material_id']==identifier
    assert calculate_materials(materials,MaterialItem(protection='fragile',item_type='tv'))['status']=='needs_review'
    mattress=[rate(),rate('queen',item_type='mattress',variant='queen')]
    assert calculate_materials(mattress,MaterialItem(protection='fabric',item_type='mattress'))['status']=='needs_review'
    assert calculate_materials(mattress,MaterialItem(protection='fabric',item_type='mattress',variant='queen'))['lines'][0]['material_id']=='queen'


def test_no_guess_on_conflict_or_missing_and_no_double_charge():
    item=MaterialItem(protection='both')
    result=calculate_materials([rate(protection='both')],item)
    assert len(result['lines'])==1
    assert result['packing_and_material']==22
    assert calculate_materials([],item)['packing_only'] is None
    assert calculate_materials([rate('a'),rate('b')],MaterialItem(protection='fabric'))['status']=='needs_review'


def test_units_and_price_changes():
    material=rate(material=2,labor=Decimal('1.50'),unit='foot',units_per_item=6)
    item=MaterialItem(protection='fabric',quantity=2)
    assert calculate_materials([material],item)['packing_and_material']==42
    material.material_price=3
    assert calculate_materials([material],item)['packing_and_material']==54


def test_invalid_rules_and_manual_rates():
    with pytest.raises(ValidationError):
        MaterialRule(measure='cubic_feet',minimum=26,maximum=25)
    with pytest.raises(ValidationError):
        MaterialItem(protection='fabric',quantity=-1)
    material=rate()
    material.rule=None
    assert calculate_materials([material],MaterialItem(protection='fabric'))['status']=='needs_review'


@pytest.mark.parametrize('volume,expected', [(1,'small'),(2,'small'),(2.01,'medium'),(3,'medium'),(4,'large'),(5,'large')])
def test_capacity_selects_smallest_box_without_opt_in(volume,expected):
    rows=[MaterialRate(id=id,name=name,material_price=price,packing_price=5,unpacking_price=15,rule=None)
          for id,name,price in [('small','Small Box: 2 Cuft',10),('medium','Medium Box: 3.0 Cuft',12),('large','Large Box: 5 Cuft',12)]]
    quote=calculate_materials(rows,MaterialItem(protection='fragile',cubic_feet=volume,quantity=2))
    assert quote['status']=='priced'
    assert quote['lines'][0]['material_id']==expected
    assert quote['lines'][0]['quantity']==2
    assert quote['packing_only']==10


def test_special_box_category_and_changed_capacity():
    generic=MaterialRate(id='small',name='Small Box: 2 Cuft',material_price=10,packing_price=6,unpacking_price=15)
    books=MaterialRate(id='books',name='Book Box: 2 CU',material_price=9,packing_price=5,unpacking_price=15)
    quote=calculate_materials([generic,books],MaterialItem(protection='fragile',item_type='books',cubic_feet=2))
    assert quote['lines'][0]['material_id']=='books'
    assert quote['packing_and_material']==14
    assert calculate_materials([generic],MaterialItem(protection='fragile',cubic_feet=3))['status']=='needs_review'
    generic.box_capacity_cuft=Decimal(4)
    assert calculate_materials([generic],MaterialItem(protection='fragile',cubic_feet=3))['status']=='priced'
    assert calculate_materials([generic],MaterialItem(protection='fragile'))['status']=='needs_review'
