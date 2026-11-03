"""Long carry charges, independently priced at each address."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field

LONG_CARRY_PREFIX = '__long_carry_pricing__:'


class LongCarryCard(BaseModel):
    enabled: bool = False
    increment_feet: int = Field(gt=0, le=100000)
    included_feet: int = Field(ge=0, le=100000)
    rate_per_cuft: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    minimum_cubic_feet: int | None = Field(default=None, ge=0, le=1000000)
    pickup_discount_percent: Decimal = Field(default=0, ge=0, le=100, max_digits=5, decimal_places=2)
    delivery_discount_percent: Decimal = Field(default=0, ge=0, le=100, max_digits=5, decimal_places=2)


def long_carry_card(services):
    for service in services:
        if service.comments.startswith(LONG_CARRY_PREFIX):
            return LongCarryCard.model_validate_json(service.comments[len(LONG_CARRY_PREFIX):])
    return None


FIELDS = ('enabled', 'included_feet', 'increment_feet', 'rate_per_cuft', 'minimum_cubic_feet',
          'pickup_discount_percent', 'delivery_discount_percent')


def plan_long_carry_card(plan):
    """The plan's long carry pricing, read from pricing_long_carry."""
    row = plan.long_carry
    if row is None:
        return None
    return LongCarryCard(**{field: getattr(row, field) for field in FIELDS})


def long_carry_service_row(plan):
    """The card as the pricing API presents it: a service row holding its settings."""
    card = plan_long_carry_card(plan)
    if card is None:
        return None
    config = {field: format(value.normalize(), 'f') if isinstance(value, Decimal) else value
              for field, value in card.model_dump().items()}
    return {'id': f'long-carry:{plan.id}', 'name': 'Long carry pricing', 'rate_text': '',
            'comments': LONG_CARRY_PREFIX + json.dumps(config), 'sort_order': -1}


def save_long_carry_card(plan, card):
    """Replace the plan's long carry pricing; None removes it."""
    from models import PricingLongCarry
    if card is None:
        plan.long_carry = None
        return
    row = plan.long_carry or PricingLongCarry()
    for field in FIELDS:
        setattr(row, field, getattr(card, field))
    plan.long_carry = row


def migrate_long_carry_cards(connection):
    """Move each plan's card from its pricing_services JSON row into pricing_long_carry, once."""
    from sqlalchemy import inspect, text
    from models import PricingLongCarry
    if inspect(connection).has_table(PricingLongCarry.__tablename__):
        return 0
    PricingLongCarry.__table__.create(connection)
    moved = set()
    rows = connection.execute(text(
        "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
        {'prefix': LONG_CARRY_PREFIX + '%'}).all()
    for service_id, plan_id, comments in rows:
        # Pricing used the first card of a plan; any later copies were never read.
        if plan_id not in moved:
            card = LongCarryCard.model_validate_json(comments[len(LONG_CARRY_PREFIX):])
            connection.execute(PricingLongCarry.__table__.insert().values(
                plan_id=plan_id, **{field: getattr(card, field) for field in FIELDS}))
            moved.add(plan_id)
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)


def long_carry_quote(card, addresses, saved, volume, move_minimum):
    if not card or not card.enabled:
        return None
    minimum = move_minimum if card.minimum_cubic_feet is None else card.minimum_cubic_feet
    billable = max(volume, minimum)
    locations = []
    for location in ('pickup', 'delivery'):
        address = addresses.get(location, '')
        revision = hashlib.sha256(json.dumps([location, address.strip().lower()]).encode()).hexdigest()
        answer = saved.get(location) or {}
        unknown = answer.get('revision') == revision and answer.get('unknown') is True and answer.get('acknowledged') is True
        distance_feet = answer.get('distance_feet') if answer.get('revision') == revision else None
        if type(distance_feet) is not int or not 0 <= distance_feet <= 100000:
            distance_feet = None
        if unknown:
            distance_feet = None
        paid = (max(0, distance_feet - card.included_feet) + card.increment_feet - 1) // card.increment_feet if distance_feet is not None else 0
        subtotal = (card.rate_per_cuft * billable * paid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        percent = getattr(card, location + '_discount_percent')
        discount = (subtotal * percent / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amount = subtotal - discount
        locations.append({'location': location, 'address': address, 'revision': revision, 'distance_feet': distance_feet,
                          'unknown': unknown, 'acknowledged': unknown,
                          'paid_increments': paid, 'subtotal': float(subtotal), 'discount_percent': float(percent), 'discount_amount': float(discount), 'total': float(amount),
                          'question': f'About how far will the movers carry your belongings between the parked truck and the entrance at {location}?',
                          'description': f'{distance_feet if distance_feet is not None else "Unanswered"} feet at {location}; first {card.included_feet} feet included. {paid} additional {card.increment_feet}-foot increments x {billable} cu ft x ${card.rate_per_cuft:.2f}.'})
    return {'increment_feet': card.increment_feet, 'included_feet': card.included_feet,
            'rate_per_cuft': float(card.rate_per_cuft), 'cubic_feet': billable,
            'inventory_cubic_feet': volume, 'minimum_cubic_feet': minimum, 'locations': locations,
            'total': float(sum(Decimal(str(row['total'])) for row in locations))}
