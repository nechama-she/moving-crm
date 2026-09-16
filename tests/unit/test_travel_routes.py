import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import travel_routes as routes


@pytest.fixture(autouse=True)
def clear_cache():
    routes.locate.cache_clear()
    yield
    routes.locate.cache_clear()


def test_straight_line_distance():
    assert routes.straight_line_miles((0, 0), (0, 1)) == Decimal('69.09')
    assert routes.straight_line_miles((39, -77), (39, -77)) == 0


def test_two_legs_and_sixty_mph_rule():
    locations = {'office': (0, 0, 'address', 'office'), 'pickup': (0, 1, 'address', 'pickup'), 'delivery': (0, 2, 'zip', 'delivery')}
    with patch.object(routes, 'locate', side_effect=lambda address: locations[address]):
        result = routes.estimate_travel('office', 'pickup', 'delivery')
    assert result['office_to_pickup_miles'] == Decimal('69.09')
    assert result['delivery_to_office_miles'] == Decimal('138.19')
    assert result['total_miles'] == Decimal('207.28')
    assert result['total_minutes'] == result['total_miles']
    assert result['travel_hours'] == result['total_miles'] / 60
    assert result['uses_zip_centers']
    assert result['method'] == 'straight_line'


def test_address_lookup_is_account_free_and_cached():
    response = MagicMock()
    response.json.return_value = {'result': {'addressMatches': [{'coordinates': {'x': -77, 'y': 39}, 'matchedAddress': '123 MAIN ST'}]}}
    with patch.object(routes.httpx, 'get', return_value=response) as get:
        first = routes.locate('123 Main St, Rockville MD 20850')
        assert routes.locate('123 Main St, Rockville MD 20850') == first
    get.assert_called_once()
    assert first == (39, -77, 'address', '123 MAIN ST')
    assert get.call_args.args[0] == routes.CENSUS_URL
    assert 'key' not in get.call_args.kwargs['params']


def test_zip_only_lookup():
    response = MagicMock(); response.status_code = 200
    response.json.return_value = {'places': [{'latitude': '39', 'longitude': '-77'}]}
    with patch.object(routes.httpx, 'get', return_value=response) as get:
        result = routes.locate('20850')
    assert result == (39, -77, 'zip', '20850')
    get.assert_called_once_with(routes.ZIP_URL + '20850', timeout=10)


def test_unmatched_address_falls_back_to_labeled_zip_center():
    address_response = MagicMock(); address_response.json.return_value = {'result': {'addressMatches': []}}
    zip_response = MagicMock(); zip_response.status_code = 200
    zip_response.json.return_value = {'places': [{'latitude': '39', 'longitude': '-77'}]}
    with patch.object(routes.httpx, 'get', side_effect=[address_response, zip_response]):
        assert routes.locate('123 Missing St, MD 20850')[2] == 'zip'


def test_lookup_outage_does_not_invent_zero_distance():
    with patch.object(routes.httpx, 'get', side_effect=httpx.ConnectError('unavailable')), pytest.raises(HTTPException) as error:
        routes.locate('20850')
    assert error.value.status_code == 502


def test_invalid_zip_rejected():
    response = MagicMock(); response.status_code = 404
    with patch.object(routes.httpx, 'get', return_value=response), pytest.raises(HTTPException) as error:
        routes.locate('00000')
    assert error.value.status_code == 422


def test_blank_address_rejected_without_lookup():
    with patch.object(routes, 'locate') as locate, pytest.raises(HTTPException):
        routes.estimate_travel('', '20850', '21201')
    locate.assert_not_called()
