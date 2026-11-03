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


def plan_shuttle_card(plan):
    """The plan's shuttle pricing, read from pricing_shuttle and pricing_shuttle_areas."""
    row = plan.shuttle
    if row is None:
        return None
    # Areas by state, alphabetical; any blank ZIP code means the whole state.
    areas = {}
    for area in row.areas:
        zips = areas.setdefault(area.state, [])
        if zips is not None:
            zip_code = (area.zip_code or '').strip()
            areas[area.state] = None if not zip_code else zips + [zip_code]
    return ShuttleCard(enabled=row.enabled, rate=row.rate, access_distance_ft=row.access_distance_ft,
                       minimum_cubic_feet=row.minimum_cubic_feet,
                       areas=[ShuttleArea(state=state, zip_codes=sorted(zips or [])) for state, zips in sorted(areas.items())])


def shuttle_service_row(plan):
    """The card as the pricing API presents it: a service row holding its settings."""
    card = plan_shuttle_card(plan)
    if card is None:
        return None
    config = {'enabled': card.enabled, 'rate': format(card.rate.normalize(), 'f'),
              'access_distance_ft': card.access_distance_ft, 'minimum_cubic_feet': card.minimum_cubic_feet,
              'areas': [area.model_dump() for area in card.areas]}
    return {'id': f'shuttle:{plan.id}', 'name': 'Delivery shuttle', 'rate_text': '',
            'comments': SHUTTLE_PREFIX + json.dumps(config), 'sort_order': -1}


def save_shuttle_card(plan, card):
    """Replace the plan's shuttle pricing; None removes it."""
    from models import PricingShuttle, PricingShuttleArea
    if card is None:
        plan.shuttle = None
        return
    row = plan.shuttle or PricingShuttle()
    row.enabled, row.rate = card.enabled, card.rate
    row.access_distance_ft, row.minimum_cubic_feet = card.access_distance_ft, card.minimum_cubic_feet
    # Keep unchanged rows so the unique (plan_id, state, zip_code) key never collides mid-save.
    wanted = {(area.state, zip_code) for area in card.areas for zip_code in (area.zip_codes or [''])}
    row.areas[:] = [area for area in row.areas if (area.state, area.zip_code or '') in wanted]
    existing = {(area.state, area.zip_code or '') for area in row.areas}
    row.areas.extend(PricingShuttleArea(state=state, zip_code=zip_code) for state, zip_code in sorted(wanted - existing))
    plan.shuttle = row


def migrate_shuttle_cards(connection):
    """Move each plan's card from its pricing_services JSON row into the shuttle tables, once."""
    from uuid import uuid4
    from sqlalchemy import inspect, text
    from models import PricingShuttle, PricingShuttleArea
    if inspect(connection).has_table(PricingShuttle.__tablename__):
        return 0
    PricingShuttle.__table__.create(connection)
    PricingShuttleArea.__table__.create(connection)
    moved = set()
    rows = connection.execute(text(
        "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
        {'prefix': SHUTTLE_PREFIX + '%'}).all()
    for service_id, plan_id, comments in rows:
        # Pricing used the first card of a plan; any later copies were never read.
        if plan_id not in moved:
            card = ShuttleCard.model_validate_json(comments[len(SHUTTLE_PREFIX):])
            connection.execute(PricingShuttle.__table__.insert().values(
                plan_id=plan_id, enabled=card.enabled, rate=card.rate,
                access_distance_ft=card.access_distance_ft, minimum_cubic_feet=card.minimum_cubic_feet))
            for state, zip_code in sorted({(area.state, zip_code) for area in card.areas for zip_code in (area.zip_codes or [''])}):
                connection.execute(PricingShuttleArea.__table__.insert().values(
                    id=str(uuid4()), plan_id=plan_id, state=state, zip_code=zip_code))
            moved.add(plan_id)
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)


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
