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
