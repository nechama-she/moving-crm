import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from local_pricing import match_region_from_address
from pricing_addresses import _google_location, pricing_location
from pricing_addresses import with_job_locations
import json


def place(state='GA', zip_code='', country='US'):
    return {'addressComponents': [
        {'types': ['administrative_area_level_1'], 'shortText': state},
        {'types': ['postal_code'], 'shortText': zip_code},
        {'types': ['country'], 'shortText': country},
    ]}


@pytest.fixture
def google(monkeypatch):
    _google_location.cache_clear()
    request = MagicMock(return_value={'places': [place()]})
    monkeypatch.setitem(sys.modules, 'customer_addresses', SimpleNamespace(google_request=request))
    yield request
    _google_location.cache_clear()


def test_monroe_georgia_does_not_require_server_lookup(google):
    assert pricing_location('Monroe, Georgia') == ('GA', '')
    assert pricing_location('Monroe, Georgia') == ('GA', '')
    google.assert_not_called()
    assert match_region_from_address('Monroe, Georgia', ['FL', 'GA'], *pricing_location('Monroe, Georgia')) == 'GA'


def test_google_zip_selects_correct_destination_band(google):
    google.return_value = {'places': [place(zip_code='30655')]}
    state, zip_code = pricing_location('123 Main St, Monroe')
    assert match_region_from_address('123 Main St, Monroe, Georgia', ['GA (300-305)', 'GA (306-309)'], state, zip_code) == 'GA (306-309)'


def test_known_zip_does_not_need_google(google):
    assert pricing_location('Mohegan Lake, New York 10547') == ('NY', '10547')
    assert pricing_location('30655') == ('GA', '30655')
    assert pricing_location(None) == ('', '')
    google.assert_not_called()


@pytest.mark.parametrize('result', [
    {'places': []}, {'places': [place(), place('FL')]},
    {'places': [place(country='CA')]}, {'places': [place(state='')]},
    {'places': [place()], 'nextPageToken': 'more'},
])
def test_unresolved_or_ambiguous_addresses_are_rejected(google, result):
    google.return_value = result
    with pytest.raises(HTTPException) as error:
        pricing_location('Unclear address')
    assert error.value.status_code == 422


def test_provider_failure_can_be_retried(google):
    google.side_effect = [HTTPException(502, 'Address lookup unavailable'), {'places': [place()]}]
    with pytest.raises(HTTPException):
        pricing_location('123 Main St, Monroe')
    assert pricing_location('123 Main St, Monroe') == ('GA', '')


@pytest.mark.parametrize('address,expected', [
    ('California, USA', ('CA', '')),
    ('Monroe, GA, USA', ('GA', '')),
    ('Mohegan Lake, New York 10547', ('NY', '10547')),
    ('Charleston, West Virginia', ('WV', '')),
    ('Washington, DC, United States', ('DC', '')),
])
def test_explicit_states_work_when_google_is_unavailable(google, address, expected):
    google.side_effect = HTTPException(503, 'No server key')
    assert pricing_location(address) == expected
    google.assert_not_called()


def test_browser_city_coordinates_are_used_for_travel_without_server_lookup(google, monkeypatch):
    import travel_routes
    addresses = ['Rockville, MD, USA', 'Washington, DC 20002, USA', 'Maryland']
    locations = [dict(address=address, state=state, zip_code=zip_code, latitude=39-i/10, longitude=-77)
                 for i, (address, state, zip_code) in enumerate(zip(addresses, ['MD', 'DC', 'MD'], ['', '20002', '']))]
    job = SimpleNamespace(customer_packing_package=json.dumps({'pricing_locations': locations}))
    lookup = MagicMock(side_effect=AssertionError('Server geocoding must not run'))
    monkeypatch.setattr(travel_routes, 'locate', lookup)
    @with_job_locations
    def calculate(lead, job, db):
        assert pricing_location(addresses[0]) == ('MD', '')
        return travel_routes.estimate_travel(addresses[2], addresses[0], addresses[1])
    result = calculate(None, job, None)
    assert result['total_miles'] > 0
    assert 'Google Maps' in result['source']
    lookup.assert_not_called()
    google.assert_not_called()


def test_oregon_long_distance_selects_book_with_destination_coverage():
    from pickup_areas import select_pickup_plan
    from zip_state import delivery_location
    source = BACKEND / 'routes/pricing.py'
    nodes = [n for n in ast.parse(source.read_text(encoding='utf-8')).body if getattr(n, 'name', '') in ('infer_job_move_type', '_plan_destination_for_delivery')]
    for node in nodes:
        node.decorator_list = []
        node.returns = None
        for arg in node.args.args:
            arg.annotation = None
    scope = dict(delivery_location=delivery_location, select_pickup_plan=select_pickup_plan,
                 match_region_from_address=match_region_from_address, local_route_matches=lambda *args:False,
                 LocalPricingRoute=MagicMock())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    east = SimpleNamespace(company_id='co', pickup_regions='MD', name='East', rates=[SimpleNamespace(destination='GA')])
    west = SimpleNamespace(company_id='co', pickup_regions='MD', name='West', rates=[SimpleNamespace(destination='Oregon (970-979)')])
    job = SimpleNamespace(company_id='co', pickup_zip='Rockville, MD, USA', delivery_zip='Eugene, Oregon 97405')
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    assert scope['infer_job_move_type'](SimpleNamespace(company_id='co'), job, db, [east,west]) == ('Long Distance', west)


@pytest.mark.parametrize('options,state,zip_code', [
    (['FL', 'NY'], 'GA', ''), (['GA (300-305)'], 'GA', '30655'),
    (['GA (300-305)', 'GA (306-309)'], 'GA', ''), (['FL', 'NY'], '', ''),
])
def test_pricing_does_not_fall_back_to_unrelated_rate(options, state, zip_code):
    source = Path(__file__).resolve().parents[2] / 'backend/routes/pricing.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if getattr(n, 'name', '') == '_plan_destination_for_delivery')
    scope = {'PricingPlan': object, 'match_region_from_address': match_region_from_address}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    plan = SimpleNamespace(rates=[SimpleNamespace(destination=value) for value in options])
    assert scope['_plan_destination_for_delivery'](plan, '', state, zip_code) == ''
