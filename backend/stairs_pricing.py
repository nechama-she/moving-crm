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
        flights = answer.get('flights') if answer.get('revision') == revision else None
        if type(flights) is not int or not 0 <= flights <= 1000:
            flights = None
        paid = max(0, flights - card.free_flights) if flights is not None else 0
        subtotal = (card.rate_per_cuft * billable * paid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        percent = getattr(card, location + '_discount_percent')
        discount = (subtotal * percent / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amount = subtotal - discount
        locations.append({'location': location, 'address': address, 'revision': revision, 'flights': flights,
                          'paid_flights': paid, 'subtotal': float(subtotal), 'discount_percent': float(percent), 'discount_amount': float(discount), 'total': float(amount),
                          'question': f'How many flights of outdoor or shared-building stairs will the movers need to use at {location}?',
                          'description': f'{flights if flights is not None else "Unanswered"} flights at {location}; {card.free_flights} free, {paid} billable × {billable} cu ft × ${card.rate_per_cuft:.2f}. Up to {card.steps_per_flight} steps per flight. Excludes stairs inside the home.'})
    return {'steps_per_flight': card.steps_per_flight, 'free_flights': card.free_flights,
            'rate_per_cuft': float(card.rate_per_cuft), 'cubic_feet': billable,
            'inventory_cubic_feet': volume, 'minimum_cubic_feet': minimum, 'locations': locations,
            'total': float(sum(Decimal(str(row['total'])) for row in locations))}
