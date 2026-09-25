"""Delivery shuttle configuration stored in the pricing book's service rows."""
import hashlib
import json
import re
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from pickup_areas import STATES

SHUTTLE_PREFIX = '__delivery_shuttle__:'


def zip_bounds(value):
    parts = re.split(r'\s*[-–]\s*', value.strip().upper())
    if len(parts) not in (1, 2) or any(not re.fullmatch(r'\d{1,5}X{0,4}', part) or len(part) != 5 for part in parts):
        raise ValueError('Use ZIP codes or ranges such as 13544, 111XX, or 111XX-12XXX')
    low, high = int(parts[0].replace('X', '0')), int(parts[-1].replace('X', '9'))
    if low > high:
        raise ValueError('ZIP range must start before it ends')
    return low, high


class ShuttleArea(BaseModel):
    state: str
    zip_codes: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator('state')
    @classmethod
    def state_code(cls, value):
        value = value.strip().upper()
        if value not in STATES:
            raise ValueError('Choose a valid state')
        return value

    @field_validator('zip_codes')
    @classmethod
    def zip_rules(cls, values):
        result = []
        for value in values:
            value = value.strip().upper()
            if not value:
                continue
            zip_bounds(value)
            if value not in result:
                result.append(value)
        return result


class ShuttleCard(BaseModel):
    enabled: bool = False
    rate: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    access_distance_ft: int = Field(gt=0, le=100000)
    minimum_cubic_feet: int | None = Field(default=None, ge=0, le=1000000)
    areas: list[ShuttleArea] = Field(default_factory=list, max_length=200)


def shuttle_card(services):
    for service in services:
        if service.comments.startswith(SHUTTLE_PREFIX):
            return ShuttleCard.model_validate_json(service.comments[len(SHUTTLE_PREFIX):])
    return None


def area_matches(areas, state, zip_code):
    for area in areas:
        if area.state != (state or '').upper():
            continue
        if not area.zip_codes:
            return True
        if re.fullmatch(r'\d{5}', zip_code or '') and any(low <= int(zip_code) <= high for low, high in map(zip_bounds, area.zip_codes)):
            return True
    return False


def shuttle_option(card, address, state, zip_code, volume, move_minimum, stored):
    if not card or not card.enabled:
        return None
    # A different address or access distance requires a fresh customer answer.
    revision = hashlib.sha256(json.dumps([address.strip().lower(), card.access_distance_ft, 'direct-front-access']).encode()).hexdigest()
    answer = stored.get('answer') if stored.get('revision') == revision else None
    automatic = area_matches(card.areas, state, zip_code)
    minimum = move_minimum if card.minimum_cubic_feet is None else card.minimum_cubic_feet
    billable = max(volume, minimum)
    return {'automatic': automatic, 'answer': answer, 'revision': revision,
            'required': automatic or answer is False, 'rate': float(card.rate),
            'inventory_cubic_feet': volume, 'minimum_cubic_feet': minimum, 'cubic_feet': billable,
            'total': float((card.rate * billable).quantize(Decimal('0.01'))),
            'question': 'Can a semi-trailer reach and park directly in front of your delivery address?'}
