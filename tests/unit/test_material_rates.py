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
