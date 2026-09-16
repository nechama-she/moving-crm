"""Account-free approximate office mileage; no live routing or traffic service."""
import math
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

import httpx
from fastapi import HTTPException

CENSUS_URL = 'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress'
ZIP_URL = 'https://api.zippopotam.us/us/'


def valid_coordinates(latitude, longitude):
    lat, lon = float(latitude), float(longitude)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Invalid coordinates')
    return lat, lon


@lru_cache(maxsize=4096)
def locate(address):
    """Use a Census address match or a labeled ZIP centroid fallback."""
    zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
    try:
        if re.search(r'[A-Za-z]', address):
            response = httpx.get(CENSUS_URL, params={'address': address, 'benchmark': 'Public_AR_Current', 'format': 'json'}, timeout=10)
            response.raise_for_status()
            matches = response.json().get('result', {}).get('addressMatches', [])
            if len(matches) == 1:
                coordinates = matches[0]['coordinates']
                lat, lon = valid_coordinates(coordinates['y'], coordinates['x'])
                return lat, lon, 'address', matches[0].get('matchedAddress') or address
        if zip_match:
            response = httpx.get(ZIP_URL + zip_match.group(1), timeout=10)
            if response.status_code == 404:
                raise HTTPException(422, 'That ZIP code could not be located. Check the address and retry.')
            response.raise_for_status()
            places = response.json().get('places') or []
            if places:
                lat, lon = valid_coordinates(places[0]['latitude'], places[0]['longitude'])
                return lat, lon, 'zip', zip_match.group(1)
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(502, 'The location lookup is unavailable. Please retry.') from exc
    raise HTTPException(422, 'Could not locate this address. Add a valid US ZIP code or full street address.')


def straight_line_miles(start, end):
    lat1, lon1 = map(math.radians, start[:2])
    lat2, lon2 = map(math.radians, end[:2])
    haversine = math.sin((lat2 - lat1) / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2)**2
    distance = 3958.7613 * 2 * math.asin(math.sqrt(max(0, min(1, haversine))))
    return Decimal(str(distance)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def estimate_travel(office, pickup, delivery):
    addresses = [(value or '').strip() for value in (office, pickup, delivery)]
    if any(not value for value in addresses):
        raise HTTPException(400, 'Enter the company office, pickup, and delivery addresses before estimating travel.')
    with ThreadPoolExecutor(max_workers=3) as pool:
        office_location, pickup_location, delivery_location = list(pool.map(locate, addresses))
    outbound = straight_line_miles(office_location, pickup_location)
    inbound = straight_line_miles(delivery_location, office_location)
    total = outbound + inbound
    return {'office_address': addresses[0], 'pickup_address': addresses[1], 'delivery_address': addresses[2],
            'office_to_pickup_miles': outbound, 'delivery_to_office_miles': inbound,
            'total_miles': total, 'total_minutes': total, 'travel_hours': total / 60,
            'source': 'US Census / Zippopotam.us', 'method': 'straight_line',
            'uses_zip_centers': any(location[2] == 'zip' for location in (office_location, pickup_location, delivery_location)),
            'matched_locations': {'office': office_location[3], 'pickup': pickup_location[3], 'delivery': delivery_location[3]}}
