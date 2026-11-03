"""Pickup coverage stored in pricing_plan_pickup_areas: one row per state and ZIP code."""
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


def parse_pickup_text(value):
    """Areas from the legacy pickup_regions text: a JSON list, or free text naming states."""
    value = str(value or '').strip()
    if value.startswith('['):
        return json.loads(value)
    return [{'state': state, 'zip_codes': []} for state in dict.fromkeys(re.findall(r'\b[A-Z]{2}\b', value.upper())) if state in STATES]


def pickup_areas(plan):
    """The plan's areas, alphabetical. Any blank ZIP code means the whole state."""
    areas = {}
    for row in plan.pickup_rows:
        zips = areas.setdefault(row.state, [])
        if zips is not None:
            zip_code = (row.zip_code or '').strip()
            areas[row.state] = None if not zip_code else zips + [zip_code]
    return [{'state': state, 'zip_codes': sorted(zips or [])} for state, zips in sorted(areas.items())]


def set_pickup_areas(plan, areas):
    """Replace the plan's rows, keeping unchanged ones so the unique key never collides."""
    from models import PricingPickupArea
    wanted = {(area['state'], zip_code) for area in areas for zip_code in (area['zip_codes'] or [''])}
    plan.pickup_rows[:] = [row for row in plan.pickup_rows if (row.state, row.zip_code or '') in wanted]
    existing = {(row.state, row.zip_code or '') for row in plan.pickup_rows}
    plan.pickup_rows.extend(PricingPickupArea(state=state, zip_code=zip_code)
                            for state, zip_code in sorted(wanted - existing))


def pickup_summary(areas):
    if not areas:
        return ''
    return 'Pick up from - ' + '; '.join(area['state'] + (' (' + ', '.join(area['zip_codes']) + ')' if area['zip_codes'] else ' (all ZIP codes)') for area in areas)


def pickup_match_score(areas, state, zip_code=''):
    matches = [area for area in areas if area['state'] == state.upper()]
    if any(area['zip_codes'] and zip_code in area['zip_codes'] for area in matches):
        return 2
    if any(not area['zip_codes'] for area in matches):
        return 1
    return 0


def select_pickup_plan(plans, state, zip_code=''):
    candidates = [(pickup_match_score(pickup_areas(plan), state, zip_code), plan) for plan in plans]
    return max((pair for pair in candidates if pair[0]), key=lambda pair: pair[0], default=(0, None))[1]


def migrate_pickup_regions(connection):
    """Copy every plan's pickup_regions text into rows, then drop the column."""
    from uuid import uuid4
    from sqlalchemy import text
    from models import PricingPickupArea
    PricingPickupArea.__table__.create(connection, checkfirst=True)
    column = connection.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'pricing_plans' AND column_name = 'pickup_regions'"
    )).first()
    if not column:
        return 0
    copied = 0
    for plan_id, value in connection.execute(text('SELECT id, pickup_regions FROM pricing_plans')).all():
        rows = {(area['state'], zip_code) for area in parse_pickup_text(value)
                for zip_code in (area.get('zip_codes') or [''])}
        for state, zip_code in sorted(rows):
            connection.execute(PricingPickupArea.__table__.insert().values(
                id=str(uuid4()), plan_id=plan_id, state=state, zip_code=zip_code))
            copied += 1
    connection.execute(text('ALTER TABLE pricing_plans DROP COLUMN pickup_regions'))
    return copied
