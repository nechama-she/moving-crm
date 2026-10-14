import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from pickup_areas import PickupArea, pickup_areas, pickup_summary, pickup_match_score, select_pickup_plan


def test_existing_pickup_states_are_preserved():
    rows = pickup_areas('Pick up from - MD, DC, DE, VA, NJ, NY, CT, RI, MA, PA, WV, MA, NC, SC, GA, FL, Tn')
    assert [row['state'] for row in rows] == 'MD DC DE VA NJ NY CT RI MA PA WV NC SC GA FL TN'.split()
    assert all(row['zip_codes'] == [] for row in rows)


def test_zip_restrictions_and_leading_zero_roundtrip():
    value = json.dumps([PickupArea(state=' nj ', zip_codes=['07001', '07002', '07001']).model_dump()])
    assert pickup_areas(value)[0]['zip_codes'] == ['07001', '07002']
    assert pickup_match_score(value, 'NJ', '07001') == 2
    assert pickup_match_score(value, 'NJ', '07003') == 0
    assert pickup_match_score(value, 'NJ') == 0
    assert pickup_match_score(value, 'NY', '07001') == 0
    assert '07001' in pickup_summary(value)


@pytest.mark.parametrize('state,zips', [('XX', []), ('MD', ['2085']), ('MD', ['20850-1234']), ('MD', ['abcde'])])
def test_invalid_pickup_area_is_rejected(state, zips):
    with pytest.raises(ValidationError):
        PickupArea(state=state, zip_codes=zips)


def test_specific_zip_book_wins_and_unsupported_pickup_has_no_fallback():
    whole = SimpleNamespace(name='East', pickup_regions='MD')
    specific = SimpleNamespace(name='Special area', pickup_regions=json.dumps([{'state': 'MD', 'zip_codes': ['20850']}]))
    assert select_pickup_plan([whole, specific], 'MD', '20850') is specific
    assert select_pickup_plan([whole, specific], 'MD', '20852') is whole
    assert select_pickup_plan([specific], 'MD', '20852') is None
    assert select_pickup_plan([whole, specific], 'FL', '33101') is None
    assert pickup_match_score('[]', 'MD', '20850') == 0


def test_pickup_coverage_database_roundtrip_and_api_summary():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, PricingPlan
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    areas = [{'state': 'NJ', 'zip_codes': ['07001']}, {'state': 'MD', 'zip_codes': []}]
    with Session(engine) as db:
        db.add(PricingPlan(id='pickup-test', source_key='pickup-test', name='East', company_name='Test Company',
                          source_file='', source_sheet='', pickup_regions=json.dumps(areas)))
        db.commit()
        db.expire_all()
        saved = db.get(PricingPlan, 'pickup-test')
        result = saved.to_dict()
        assert result['pickup_areas'] == areas
        assert 'NJ (07001)' in result['pickup_regions']
        assert 'MD (all ZIP codes)' in result['pickup_regions']
    engine.dispose()
