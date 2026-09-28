import sys
from pathlib import Path
import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from long_distance_packing import PackingCard


def test_material_rates_preserved_with_packing():
    card = PackingCard.model_validate({'full':'2.50', 'materials':[
        {'id':'tape','name':'Tape','material_price':'3','packing_price':'0','unpacking_price':'0'}]})
    saved = PackingCard.model_validate_json(card.model_dump_json())
    assert saved.materials[0].material_price == 3
    assert saved.full == card.full
    assert PackingCard().materials == []


@pytest.mark.parametrize('patch', [{'name':' '}, {'material_price':'-1'}, {'packing_price':'NaN'}, {'unpacking_price':'1.001'}])
def test_invalid_material_rates_rejected(patch):
    row = {'id':'box','name':'Box','material_price':'9','packing_price':'5','unpacking_price':'15',**patch}
    with pytest.raises(ValidationError):
        PackingCard(materials=[row])


def test_duplicate_material_ids_rejected():
    row = {'id':'box','name':'Box','material_price':'9','packing_price':'5','unpacking_price':'15'}
    with pytest.raises(ValidationError):
        PackingCard(materials=[row,row])


def test_capacity_units_are_saved_and_size_rules_follow_capacity():
    from long_distance_packing import MaterialRate
    base={'id':'test','name':'Test','material_price':10,'packing_price':5,'unpacking_price':0}
    box=MaterialRate(**base,capacity=2,capacity_unit='cuft')
    assert box.box_capacity_cuft==2
    assert box.rule.maximum==2
    tv=MaterialRate(**base,capacity=65,capacity_unit='inches')
    assert tv.rule.measure=='screen_inches'
    assert tv.rule.maximum==65
    assert tv.box_capacity_cuft is None
    paper=MaterialRate(**base,capacity=100,capacity_unit='sheets')
    assert MaterialRate.model_validate_json(paper.model_dump_json()).capacity==100
    assert paper.rule is None
    large=MaterialRate(**base,capacity=65,capacity_unit='inches',capacity_kind='over')
    assert large.rule.minimum==65
    assert not large.rule.minimum_inclusive


def test_mattress_size_round_trip_and_matching():
    from long_distance_packing import MaterialRate
    from material_calculation import calculate_materials, MaterialItem
    rows=[MaterialRate(id=size,name='Bag',material_price=26,packing_price=12,unpacking_price=15,
                      capacity_unit='mattress_size',mattress_size=size) for size in ('twin','full','queen','king')]
    rows=[MaterialRate.model_validate_json(row.model_dump_json()) for row in rows]
    result=calculate_materials(rows,MaterialItem(protection='fabric',item_type='mattress',variant='queen'))
    assert result['lines'][0]['material_id']=='queen'
    assert result['packing_and_material']==38
    assert result['packing_only']==12
    with pytest.raises(ValidationError):
        MaterialRate(id='bad',name='Bag',material_price=1,packing_price=1,unpacking_price=1,capacity_unit='mattress_size')
