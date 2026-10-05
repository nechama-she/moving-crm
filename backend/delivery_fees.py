"""Pricing-book delivery fees based on Google driving-route mileage."""
import hashlib
import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from shuttle import ShuttleArea, area_matches, zip_bounds
from zip_state import delivery_location

DELIVERY_FEE_PREFIX = '__delivery_mileage__:'
ORIGIN_FEE_PREFIX = '__origin_mileage__:'


class DeliveryFeeRule(ShuttleArea):
    origin_zip: str
    rate_per_mile: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

    @field_validator('origin_zip')
    @classmethod
    def valid_origin(cls, value):
        value = value.strip()
        if not re.fullmatch(r'\d{5}', value):
            raise ValueError('Enter a five-digit starting ZIP code')
        return value


class DeliveryFeeCard(BaseModel):
    enabled: bool = False
    rules: list[DeliveryFeeRule] = Field(default_factory=list, max_length=200)


def delivery_fee_card(services, prefix=DELIVERY_FEE_PREFIX):
    for service in services:
        if service.comments.startswith(prefix):
            return DeliveryFeeCard.model_validate_json(service.comments[len(prefix):])
    return None


def matching_rule(card, address):
    if not card or not card.enabled:
        return None
    state, zip_code = delivery_location(address)
    matches = [rule for rule in card.rules if area_matches([rule], state, zip_code)]
    # Narrower ZIP coverage wins; stable card order breaks equal-specificity ties.
    def width(rule):
        return min((high-low for low, high in map(zip_bounds, rule.zip_codes)
                    if zip_code and low <= int(zip_code) <= high), default=100000)
    return min(matches, key=width) if matches else None


def driving_meters(origin_zip, destination):
    from config import get_config
    key = str(get_config().get('GOOGLE_MAPS_SERVER_KEY') or os.getenv('GOOGLE_MAPS_SERVER_KEY', '')).strip()
    if not key:
        raise HTTPException(503, 'Google Maps routing is not configured. The mileage fee could not be calculated.')
    try:
        response = httpx.post('https://routes.googleapis.com/directions/v2:computeRoutes',
            headers={'X-Goog-Api-Key': key, 'X-Goog-FieldMask': 'routes.distanceMeters'},
            json={'origin': {'address': f'{origin_zip}, USA'},
                  'destination': {'address': destination + ', USA'},
                  'travelMode': 'DRIVE', 'routingPreference': 'TRAFFIC_UNAWARE',
                  'computeAlternativeRoutes': False}, timeout=10)
        response.raise_for_status()
        routes = response.json().get('routes') or []
        if not routes:
            raise HTTPException(422, 'Google Maps could not find a driving route. Check the customer address.')
        meters = routes[0].get('distanceMeters')
        if type(meters) is not int or meters < 0:
            raise ValueError('Invalid route distance')
        return meters
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(502, 'Google Maps could not calculate the mileage fee. Please retry; no approximate mileage was used.') from None


def delivery_fee(services, address, saved=None, *, prefix=DELIVERY_FEE_PREFIX, endpoint="delivery"):
    rule = matching_rule(delivery_fee_card(services, prefix), address)
    if not rule:
        return None
    revision = hashlib.sha256(json.dumps([rule.origin_zip, address.strip().lower(), 'DRIVE']).encode()).hexdigest()
    # Reuse this estimate's route basis until either endpoint changes. No polling.
    saved = saved or {}
    meters = saved.get('meters') if saved.get('revision') == revision else None
    if type(meters) is not int or meters < 0:
        meters = driving_meters(rule.origin_zip, address)
    miles = (Decimal(meters) / Decimal('1609.344')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    amount = (miles * rule.rate_per_mile).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'revision': revision, 'meters': meters, 'miles': str(miles), 'origin_zip': rule.origin_zip,
            'amount': amount, 'description': f'{miles:,.2f} driving miles from ZIP {rule.origin_zip} to {endpoint} at ${rule.rate_per_mile:,.2f} / mile (Google Maps)'}


def origin_fee_card(services):
    return delivery_fee_card(services, ORIGIN_FEE_PREFIX)


def origin_fee(services, address, saved=None):
    return delivery_fee(services, address, saved, prefix=ORIGIN_FEE_PREFIX, endpoint="pickup")
