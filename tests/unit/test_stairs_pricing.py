import sys
from pathlib import Path
import pytest
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from stairs_pricing import StairsCard, stairs_quote


def quote(pickup, delivery, **params):
    card = StairsCard(enabled=True, steps_per_flight=13, free_flights=1, rate_per_cuft='.20', **params)
    initial = stairs_quote(card, {}, {}, 24, 286)
    saved = {r['location']: {'revision': r['revision'], 'flights': n} for r,n in zip(initial['locations'], [pickup,delivery])}
    return card, saved, stairs_quote(card, {}, saved, 24, 286)


@pytest.mark.parametrize('pickup,delivery,total', [(0,0,0),(1,1,0),(2,1,57.2),(2,2,114.4),(3,2,171.6)])
def test_each_address_has_its_own_allowance(pickup,delivery,total):
    assert quote(pickup,delivery)[2]['total'] == total


def test_full_pickup_discount_preserves_original_charge():
    card,saved,result = quote(2,2,pickup_discount_percent=100)
    pickup,delivery = result['locations']
    assert (pickup['subtotal'],pickup['discount_amount'],pickup['total']) == (57.2,57.2,0)
    assert delivery['total'] == result['total'] == 57.2
    changed = stairs_quote(card, {'delivery':'new address'}, saved, 24, 286)
    assert changed['locations'][0]['flights'] == 2
    assert changed['locations'][1]['flights'] is None


def test_partial_discount_and_volume():
    assert quote(2,2,pickup_discount_percent=25,delivery_discount_percent=50)[2]['total'] == 71.5
    card,saved,_ = quote(2,0)
    assert stairs_quote(card, {}, saved, 500, 286)['total'] == 100
    assert stairs_quote(card.model_copy(update={'steps_per_flight':14}), {}, saved, 500, 286)['locations'][0]['flights'] is None


@pytest.mark.parametrize('percent', [-1,101])
def test_invalid_discount_rejected(percent):
    with pytest.raises(ValidationError): quote(2,2,pickup_discount_percent=percent)
