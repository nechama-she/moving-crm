import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from pickup_areas import PickupArea, parse_pickup_text, pickup_areas, pickup_summary, pickup_match_score, select_pickup_plan, set_pickup_areas, migrate_pickup_regions


def plan(name, *rows):
    return SimpleNamespace(name=name, pickup_rows=[SimpleNamespace(state=state, zip_code=zip_code) for state, zip_code in rows])


def test_legacy_pickup_text_is_parsed():
    rows = parse_pickup_text('Pick up from - MD, DC, DE, VA, NJ, NY, CT, RI, MA, PA, WV, MA, NC, SC, GA, FL, Tn')
    assert [row['state'] for row in rows] == 'MD DC DE VA NJ NY CT RI MA PA WV NC SC GA FL TN'.split()
    assert all(row['zip_codes'] == [] for row in rows)


def test_rows_are_alphabetical_and_any_blank_zip_is_whole_state():
    book = plan('East', ('NJ', '07002'), ('MD', ''), ('NJ', '07001'), ('VA', None), ('VA', '22030'), ('DC', '  '))
    assert pickup_areas(book) == [{'state': 'DC', 'zip_codes': []}, {'state': 'MD', 'zip_codes': []},
                                  {'state': 'NJ', 'zip_codes': ['07001', '07002']}, {'state': 'VA', 'zip_codes': []}]


def test_zip_restrictions_and_leading_zero_roundtrip():
    area = PickupArea(state=' nj ', zip_codes=['07001', '07002', '07001']).model_dump()
    assert area['zip_codes'] == ['07001', '07002']
    areas = pickup_areas(plan('East', ('NJ', '07001'), ('NJ', '07002')))
    assert pickup_match_score(areas, 'NJ', '07001') == 2
    assert pickup_match_score(areas, 'NJ', '07003') == 0
    assert pickup_match_score(areas, 'NJ') == 0
    assert pickup_match_score(areas, 'NY', '07001') == 0
    assert '07001' in pickup_summary(areas)


@pytest.mark.parametrize('state,zips', [('XX', []), ('MD', ['2085']), ('MD', ['20850-1234']), ('MD', ['abcde'])])
def test_invalid_pickup_area_is_rejected(state, zips):
    with pytest.raises(ValidationError):
        PickupArea(state=state, zip_codes=zips)


def test_specific_zip_book_wins_and_unsupported_pickup_has_no_fallback():
    whole = plan('East', ('MD', ''))
    specific = plan('Special area', ('MD', '20850'))
    assert select_pickup_plan([whole, specific], 'MD', '20850') is specific
    assert select_pickup_plan([whole, specific], 'MD', '20852') is whole
    assert select_pickup_plan([specific], 'MD', '20852') is None
    assert select_pickup_plan([whole, specific], 'FL', '33101') is None
    assert pickup_match_score([], 'MD', '20850') == 0


def test_book_without_pickup_states_covers_nothing():
    assert select_pickup_plan([plan('MD, VA')], 'VA') is None


def test_pickup_coverage_database_roundtrip_and_api_summary():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, PricingPlan, PricingPickupArea
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        book = PricingPlan(id='pickup-test', source_key='pickup-test', name='East', company_name='Test Company',
                           source_file='', source_sheet='')
        set_pickup_areas(book, [{'state': 'NJ', 'zip_codes': ['07001']}, {'state': 'MD', 'zip_codes': []}])
        db.add(book)
        db.commit()
        db.expire_all()
        result = db.get(PricingPlan, 'pickup-test').to_dict()
        assert result['pickup_areas'] == [{'state': 'MD', 'zip_codes': []}, {'state': 'NJ', 'zip_codes': ['07001']}]
        assert result['pickup_regions'] == 'Pick up from - MD (all ZIP codes); NJ (07001)'
        # Saving again keeps unchanged rows, so the unique key never collides.
        saved = db.get(PricingPlan, 'pickup-test')
        kept = {row.id for row in saved.pickup_rows if row.state == 'MD'}
        set_pickup_areas(saved, [{'state': 'MD', 'zip_codes': []}, {'state': 'NJ', 'zip_codes': ['07002']}])
        db.commit()
        db.expire_all()
        rows = db.query(PricingPickupArea).filter_by(plan_id='pickup-test').all()
        assert sorted((row.state, row.zip_code) for row in rows) == [('MD', ''), ('NJ', '07002')]
        assert kept == {row.id for row in rows if row.state == 'MD'}
        db.delete(db.get(PricingPlan, 'pickup-test'))
        db.commit()
        assert db.query(PricingPickupArea).count() == 0
    engine.dispose()
