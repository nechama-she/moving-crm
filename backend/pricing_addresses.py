"""Resolve pricing locations using Google when the saved address lacks a ZIP."""
import time
from functools import lru_cache

from fastapi import HTTPException

from zip_state import STATE_CODES, delivery_location


def pricing_location(value: str | None) -> tuple[str, str]:
    address = (value or '').strip()
    if not address:
        return '', ''
    state, zip_code = delivery_location(address)
    if state and zip_code:
        return state, zip_code
    return _google_location(address, int(time.time() // 3600))


@lru_cache(maxsize=1024)
def _google_location(address: str, cache_hour: int) -> tuple[str, str]:
    from customer_addresses import google_request

    result = google_request('POST', 'places:searchText', json={
        'textQuery': address, 'regionCode': 'US', 'languageCode': 'en', 'pageSize': 2,
    }, headers={'X-Goog-FieldMask': 'places.addressComponents,nextPageToken'})
    places = result.get('places', [])
    if len(places) != 1 or result.get('nextPageToken'):
        raise HTTPException(422, 'Could not uniquely locate this address for pricing. Select a complete address including the city and state.')
    parts = places[0].get('addressComponents', [])
    def component(kind):
        return next((part.get('shortText', '') for part in parts if kind in part.get('types', [])), '')
    state = component('administrative_area_level_1')
    if component('country') != 'US' or state not in STATE_CODES:
        raise HTTPException(422, 'Pricing requires a US address with a recognized state.')
    return state, component('postal_code')
