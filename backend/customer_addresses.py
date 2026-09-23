"""Google Places requests and signed selections. Provider credentials stay here."""
import os
import time
from urllib.parse import quote

import httpx
import jwt
from fastapi import HTTPException

from config import get_config


def google_request(method, path, **kwargs):
    key = str(get_config().get('GOOGLE_MAPS_SERVER_KEY') or os.getenv('GOOGLE_MAPS_SERVER_KEY', '')).strip()
    if not key:
        raise HTTPException(503, 'Address search is temporarily unavailable. Please try again later.')
    try:
        response = httpx.request(method, 'https://places.googleapis.com/v1/' + path,
            headers={'X-Goog-Api-Key': key, **kwargs.pop('headers', {})}, timeout=8, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        # Never return Google's error body, request headers, or credentials.
        raise HTTPException(502, 'Address search is temporarily unavailable. Please try again.') from None


def suggestions(text, session_token):
    result = google_request('POST', 'places:autocomplete', json={
        'input': text, 'sessionToken': session_token, 'includedRegionCodes': ['us'],
        'languageCode': 'en', 'includeQueryPredictions': False,
    }, headers={'X-Goog-FieldMask': 'suggestions.placePrediction.placeId,suggestions.placePrediction.text.text'})
    return [{'place_id': p['placeId'], 'text': p['text']['text']}
            for row in result.get('suggestions', [])
            if (p := row.get('placePrediction')) and p.get('placeId') and p.get('text', {}).get('text')][:5]


def resolve_address(place_id, session_token, access_id):
    place = google_request('GET', 'places/' + quote(place_id, safe=''),
        params={'sessionToken': session_token, 'languageCode': 'en'},
        headers={'X-Goog-FieldMask': 'id,formattedAddress,addressComponents'})
    parts = place.get('addressComponents', [])
    def component(kind, short=False):
        row = next((p for p in parts if kind in p.get('types', [])), {})
        return row.get('shortText' if short else 'longText', '').strip()
    address = {'place_id': place.get('id'), 'formatted_address': place.get('formattedAddress'),
        'city': component('locality') or component('postal_town') or component('sublocality_level_1'),
        'state': component('administrative_area_level_1', True), 'country': component('country', True)}
    if not all(address.values()) or address['country'] != 'US':
        raise HTTPException(400, 'Choose an address that includes a city and state.')
    proof = jwt.encode({'sub': access_id, 'aud': 'customer-address', 'exp': int(time.time()) + 3600,
                        'address': address}, os.environ['JWT_SECRET'], algorithm='HS256')
    return {**address, 'proof': proof}


def validate_selection(selection, access_id):
    try:
        claims = jwt.decode(selection.proof or '', os.environ['JWT_SECRET'], algorithms=['HS256'],
            audience='customer-address', options={'require': ['exp', 'sub', 'address']})
        if claims['sub'] != access_id or claims['address'] != selection.model_dump(exclude={'proof'}):
            raise ValueError('Selection changed')
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(400, 'Please select the address suggestion again before saving.') from None
