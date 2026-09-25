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
