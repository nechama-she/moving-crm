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


def test_monroe_georgia_resolves_using_google_and_reuses_result(google):
    assert pricing_location('Monroe, Georgia') == ('GA', '')
    assert pricing_location('Monroe, Georgia') == ('GA', '')
    google.assert_called_once()
    assert google.call_args.args == ('POST', 'places:searchText')
    assert google.call_args.kwargs['json']['textQuery'] == 'Monroe, Georgia'
    assert match_region_from_address('Monroe, Georgia', ['FL', 'GA'], *pricing_location('Monroe, Georgia')) == 'GA'


def test_google_zip_selects_correct_destination_band(google):
    google.return_value = {'places': [place(zip_code='30655')]}
    state, zip_code = pricing_location('123 Main St, Monroe, Georgia')
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
        pricing_location('Monroe, Georgia')
    assert pricing_location('Monroe, Georgia') == ('GA', '')


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
