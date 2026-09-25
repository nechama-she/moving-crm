import sys
from pathlib import Path
from decimal import Decimal
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from extra_stops import StopRate, stop_price, ExtraStopsCard

@pytest.mark.parametrize('miles,total',[(0,0),(8,0),(10,0),(11,55),(15,75),(20,100)])
def test_pickup_allowance(miles,total):
    rule=StopRate(free_miles=10,stop_fee=50,per_mile=5)
    assert stop_price(rule,Decimal(str(miles))*Decimal('1609.344'))['total']==total

@pytest.mark.parametrize('miles,total',[(0,50),(8,90),(15,125)])
def test_delivery_fee(miles,total):
    rule=StopRate(free_miles=0,stop_fee=50,per_mile=5)
    assert stop_price(rule,Decimal(str(miles))*Decimal('1609.344'))['total']==total

def test_parameters_and_partial_mile():
    rule=StopRate(free_miles=5,stop_fee=20,per_mile=2)
    assert stop_price(rule,Decimal('5.5')*Decimal('1609.344'))['total']==21
    with pytest.raises(ValueError):StopRate(free_miles=-1,stop_fee=50,per_mile=5)
