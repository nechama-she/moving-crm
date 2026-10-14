"""Pickup coverage stored in the existing pricing-plan pickup_regions field."""
import json
import re
from pydantic import BaseModel, Field, field_validator

STATES = set('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split())


class PickupArea(BaseModel):
    state: str
    zip_codes: list[str] = Field(default_factory=list, max_length=10000)

    @field_validator('state')
    @classmethod
    def valid_state(cls, value):
        value = value.strip().upper()
        if value not in STATES:
            raise ValueError('Choose a valid state')
        return value

    @field_validator('zip_codes')
    @classmethod
    def valid_zips(cls, values):
        result = []
        for value in values:
            value = value.strip()
            if not re.fullmatch(r'\d{5}', value):
                raise ValueError('Enter five-digit ZIP codes, separated by commas')
            if value not in result:
                result.append(value)
        return result


def pickup_areas(value):
    value = str(value or '').strip()
    if value.startswith('['):
        return json.loads(value)
    return [{'state': state, 'zip_codes': []} for state in dict.fromkeys(re.findall(r'\b[A-Z]{2}\b', value.upper())) if state in STATES]


def pickup_summary(value):
    areas = pickup_areas(value)
    if not areas:
        return '' if str(value or '').startswith('[') else value
    return 'Pick up from - ' + '; '.join(area['state'] + (' (' + ', '.join(area['zip_codes']) + ')' if area['zip_codes'] else ' (all ZIP codes)') for area in areas)


def pickup_match_score(value, state, zip_code=''):
    matches = [area for area in pickup_areas(value) if area['state'] == state.upper()]
    if any(area['zip_codes'] and zip_code in area['zip_codes'] for area in matches):
        return 2
    if any(not area['zip_codes'] for area in matches):
        return 1
    return 0


def select_pickup_plan(plans, state, zip_code=''):
    candidates = [(pickup_match_score(plan.pickup_regions or plan.name, state, zip_code), plan) for plan in plans]
    return max((pair for pair in candidates if pair[0]), key=lambda pair: pair[0], default=(0, None))[1]
