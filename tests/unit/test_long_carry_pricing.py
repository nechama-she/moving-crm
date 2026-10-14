import sys
from pathlib import Path
import pytest
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from long_carry_pricing import LongCarryCard, long_carry_quote

def quote(distance, **params):
    card = LongCarryCard(enabled=True, included_feet=75, increment_feet=75, rate_per_cuft='.20', **params)
    initial = long_carry_quote(card, {}, {}, 300, 0)
    saved = {'pickup': {'revision': initial['locations'][0]['revision'], 'distance_feet': distance}}
    return card, saved, long_carry_quote(card, {}, saved, 300, 0)

@pytest.mark.parametrize('distance,increments', [(0,0),(74,0),(75,0),(76,1),(100,1),(150,1),(151,2),(160,2),(225,2),(226,3)])
def test_distance_boundaries(distance,increments):
    row=quote(distance)[2]['locations'][0]
    assert row['paid_increments']==increments
    assert row['total']==increments*60

def test_discount_and_changed_address():
    card,saved,result=quote(100,pickup_discount_percent=100)
    row=result['locations'][0]
    assert (row['subtotal'],row['discount_amount'],row['total'])==(60,60,0)
    assert long_carry_quote(card,{'pickup':'Changed'},saved,300,0)['locations'][0]['distance_feet'] is None
    assert long_carry_quote(card,{},saved,24,300)['locations'][0]['subtotal']==60

def test_parameters_reprice_saved_distance():
    card,saved,_=quote(160)
    updated=card.model_copy(update={'included_feet':100,'increment_feet':30})
    assert long_carry_quote(updated,{},saved,300,0)['locations'][0]['paid_increments']==2

def test_zero_increment_rejected():
    with pytest.raises(ValidationError):
        LongCarryCard(included_feet=75,increment_feet=0,rate_per_cuft='.20')


def test_unknown_requires_acknowledgment_and_preserves_pending_distance():
    card, saved, _ = quote(150)
    saved['pickup'].update(distance_feet=None, unknown=True, acknowledged=True)
    row = long_carry_quote(card, {}, saved, 300, 0)['locations'][0]
    assert row['unknown'] and row['acknowledged']
    assert row['distance_feet'] is None
    assert row['paid_increments'] == 0
    assert not long_carry_quote(card, {'pickup': 'New address'}, saved, 300, 0)['locations'][0]['unknown']
    saved['pickup']['acknowledged'] = False
    assert not long_carry_quote(card, {}, saved, 300, 0)['locations'][0]['unknown']
