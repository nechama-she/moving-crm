"""Outdoor/shared-building stair charges, independently priced at each address."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field

STAIRS_PREFIX = '__stairs_pricing__:'


class StairsCard(BaseModel):
    enabled: bool = False
    steps_per_flight: int = Field(gt=0, le=1000)
    free_flights: int = Field(ge=0, le=1000)
    rate_per_cuft: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    minimum_cubic_feet: int | None = Field(default=None, ge=0, le=1000000)
    pickup_discount_percent: Decimal = Field(default=0, ge=0, le=100, max_digits=5, decimal_places=2)
    delivery_discount_percent: Decimal = Field(default=0, ge=0, le=100, max_digits=5, decimal_places=2)


def stairs_card(services):
    for service in services:
        if service.comments.startswith(STAIRS_PREFIX):
            return StairsCard.model_validate_json(service.comments[len(STAIRS_PREFIX):])
    return None


FIELDS = ('enabled', 'steps_per_flight', 'free_flights', 'rate_per_cuft', 'minimum_cubic_feet',
          'pickup_discount_percent', 'delivery_discount_percent')


def plan_stairs_card(plan):
    """The plan's stairs pricing, read from pricing_stairs."""
    row = plan.stairs
    if row is None:
        return None
    return StairsCard(**{field: getattr(row, field) for field in FIELDS})


def stairs_service_row(plan):
    """The card as the pricing API presents it: a service row holding its settings."""
    card = plan_stairs_card(plan)
    if card is None:
        return None
    config = {field: format(value.normalize(), 'f') if isinstance(value, Decimal) else value
              for field, value in card.model_dump().items()}
    return {'id': f'stairs:{plan.id}', 'name': 'Stairs pricing', 'rate_text': '',
            'comments': STAIRS_PREFIX + json.dumps(config), 'sort_order': -1}


def save_stairs_card(plan, card):
    """Replace the plan's stairs pricing; None removes it."""
    from models import PricingStairs
    if card is None:
        plan.stairs = None
        return
    row = plan.stairs or PricingStairs()
    for field in FIELDS:
        setattr(row, field, getattr(card, field))
    plan.stairs = row


def migrate_stairs_cards(connection):
    """Move each plan's card from its pricing_services JSON row into pricing_stairs, once."""
    from sqlalchemy import inspect, text
    from models import PricingStairs
    if inspect(connection).has_table(PricingStairs.__tablename__):
        return 0
    PricingStairs.__table__.create(connection)
    moved = set()
    rows = connection.execute(text(
        "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
        {'prefix': STAIRS_PREFIX + '%'}).all()
    for service_id, plan_id, comments in rows:
        # Pricing used the first card of a plan; any later copies were never read.
        if plan_id not in moved:
            card = StairsCard.model_validate_json(comments[len(STAIRS_PREFIX):])
            connection.execute(PricingStairs.__table__.insert().values(
                plan_id=plan_id, **{field: getattr(card, field) for field in FIELDS}))
            moved.add(plan_id)
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)


def stairs_quote(card, addresses, saved, volume, move_minimum):
    if not card or not card.enabled:
        return None
    minimum = move_minimum if card.minimum_cubic_feet is None else card.minimum_cubic_feet
    billable = max(volume, minimum)
    locations = []
    for location in ('pickup', 'delivery'):
        address = addresses.get(location, '')
        revision = hashlib.sha256(json.dumps([location, address.strip().lower(), card.steps_per_flight]).encode()).hexdigest()
        answer = saved.get(location) or {}
        unknown = answer.get('revision') == revision and answer.get('unknown') is True
        flights = answer.get('flights') if answer.get('revision') == revision else None
        if unknown or type(flights) is not int or not 0 <= flights <= 1000:
            flights = None
        paid = max(0, flights - card.free_flights) if flights is not None else 0
        subtotal = (card.rate_per_cuft * billable * paid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        percent = getattr(card, location + '_discount_percent')
        discount = (subtotal * percent / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amount = subtotal - discount
        locations.append({'location': location, 'address': address, 'revision': revision, 'flights': flights, 'unknown': unknown,
                          'paid_flights': paid, 'subtotal': float(subtotal), 'discount_percent': float(percent), 'discount_amount': float(discount), 'total': float(amount),
                          'question': f'How many flights of outdoor or shared-building stairs will the movers need to use at {location}?',
                          'description': f'{flights if flights is not None else "Unanswered"} flights at {location}; {card.free_flights} free, {paid} billable × {billable} cu ft × ${card.rate_per_cuft:.2f}. Up to {card.steps_per_flight} steps per flight. Excludes stairs inside the home.'})
    return {'steps_per_flight': card.steps_per_flight, 'free_flights': card.free_flights,
            'rate_per_cuft': float(card.rate_per_cuft), 'cubic_feet': billable,
            'inventory_cubic_feet': volume, 'minimum_cubic_feet': minimum, 'locations': locations,
            'total': float(sum(Decimal(str(row['total'])) for row in locations))}
