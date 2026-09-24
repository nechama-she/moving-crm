import sys
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from storage_pricing import StorageCard, storage_quote


@pytest.mark.parametrize('days,periods',[(0,0),(29,0),(30,0),(31,1),(35,1),(58,1),(60,1),(61,2),(68,2),(90,2),(91,3)])
def test_partial_periods_and_user_examples(days,periods):
    config=StorageCard(enabled=True,free_days=30,period_days=30,rate_per_cuft='.50')
    pickup=date(2026,9,1)
    result=storage_quote(config,pickup,(pickup+timedelta(days=days)).isoformat(),24,286)
    assert result['paid_periods']==periods
    assert result['billed_days']==periods*30
    assert result['total']==143*periods
    assert result['cubic_feet']==286 and result['inventory_cubic_feet']==24


def test_parameters_leap_year_and_invalid_dates():
    config=StorageCard(enabled=True,free_days=7,period_days=10,rate_per_cuft='2',minimum_cubic_feet=0)
    result=storage_quote(config,date(2028,2,20),'2028-03-10',24,286)
    assert result['elapsed_days']==19 and result['paid_periods']==2 and result['total']==96
    for available in ['', 'not-a-date','2028-02-19']:
        result=storage_quote(config,date(2028,2,20),available,24,286)
        assert not result['valid'] and result['total']==0
    assert not storage_quote(config,None,'2028-03-10',24,286)['valid']
    assert storage_quote(config.model_copy(update={'enabled':False}),date(2028,2,20),'2028-03-10',24,286) is None


@pytest.mark.parametrize('patch',[{'free_days':-1},{'period_days':0},{'rate_per_cuft':'-1'},{'minimum_cubic_feet':-1}])
def test_invalid_parameters_rejected(patch):
    with pytest.raises(ValueError):
        StorageCard(**{'enabled':True,'free_days':30,'period_days':30,'rate_per_cuft':Decimal('.50'),**patch})
