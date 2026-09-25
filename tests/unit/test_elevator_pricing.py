import sys
from pathlib import Path
import pytest
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from elevator_pricing import ElevatorCard, elevator_quote

def quote(volume, pickup=True, delivery=False, **params):
    card=ElevatorCard(enabled=True,threshold_cuft=500,lower_fee=150,upper_fee=250,**params)
    initial=elevator_quote(card,{}, {},volume)
    saved={r['location']:{'revision':r['revision'],'uses_elevator':answer} for r,answer in zip(initial['locations'],[pickup,delivery])}
    return card,saved,elevator_quote(card,{},saved,volume)

@pytest.mark.parametrize('volume,total',[(24,150),(499,150),(500,150),(501,250),(1000,250)])
def test_threshold(volume,total):
    assert quote(volume)[2]['total']==total

def test_each_address_and_discount():
    assert quote(500,True,True)[2]['total']==300
    card,saved,result=quote(501,True,True,pickup_discount_percent=100)
    assert result['total']==250
    assert result['locations'][0]['subtotal']==result['locations'][0]['discount_amount']==250
    assert elevator_quote(card,{'pickup':'new address'},saved,501)['locations'][0]['uses_elevator'] is None
    assert quote(501,False,False)[2]['total']==0

def test_unknown_answer_does_not_become_yes():
    assert quote(500,None,'yes')[2]['locations'][1]['uses_elevator'] is None

def test_editable_parameters_and_validation():
    card,saved,_=quote(500)
    updated=ElevatorCard(enabled=True,threshold_cuft=400,lower_fee=100,upper_fee=175)
    assert elevator_quote(updated,{},saved,500)['total']==175
    with pytest.raises(ValidationError):
        ElevatorCard(threshold_cuft=500,lower_fee=-1,upper_fee=250)


@pytest.mark.parametrize('volume,fee',[(500,150),(501,250),(1500,250),(1501,400),(3000,400)])
def test_multiple_tiers(volume,fee):
    card=ElevatorCard(enabled=True,tiers=[{'up_to_cuft':500,'fee':150},{'up_to_cuft':1500,'fee':250},{'fee':400}])
    assert elevator_quote(card,{}, {},volume)['fee']==fee

@pytest.mark.parametrize('tiers',[
    [{'up_to_cuft':500,'fee':150}],
    [{'up_to_cuft':500,'fee':150},{'up_to_cuft':500,'fee':250},{'fee':300}],
    [{'up_to_cuft':1500,'fee':150},{'up_to_cuft':500,'fee':250},{'fee':300}],
    [{'fee':150},{'fee':250}],
    [{'up_to_cuft':0,'fee':150},{'fee':250}],
])
def test_invalid_tier_ranges(tiers):
    with pytest.raises(ValidationError): ElevatorCard(tiers=tiers)

def test_legacy_settings_keep_fees_and_discounts():
    card=ElevatorCard(enabled=True,threshold_cuft=500,lower_fee=150,upper_fee=250,pickup_discount_percent=100)
    assert [t.fee for t in card.tiers]==[150,250]
    assert card.pickup_discount_percent==100
    assert ElevatorCard.model_validate_json(card.model_dump_json())==card
