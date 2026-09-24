"""Elevator charges, independently priced at each address."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field

ELEVATOR_PREFIX = '__elevator_pricing__:'


class ElevatorCard(BaseModel):
    enabled: bool = False
    threshold_cuft: int = Field(gt=0, le=1000000)
    lower_fee: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    upper_fee: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    pickup_discount_percent: Decimal = Field(default=0, ge=0, le=100, max_digits=5, decimal_places=2)
    delivery_discount_percent: Decimal = Field(default=0, ge=0, le=100, max_digits=5, decimal_places=2)


def elevator_card(services):
    for service in services:
        if service.comments.startswith(ELEVATOR_PREFIX):
            return ElevatorCard.model_validate_json(service.comments[len(ELEVATOR_PREFIX):])
    return None


def elevator_quote(card, addresses, saved, volume):
    if not card or not card.enabled:
        return None
    fee = card.lower_fee if volume <= card.threshold_cuft else card.upper_fee
    locations = []
    for location in ('pickup', 'delivery'):
        address = addresses.get(location, '')
        revision = hashlib.sha256(json.dumps([location, address.strip().lower()]).encode()).hexdigest()
        answer = saved.get(location) or {}
        uses_elevator = answer.get('uses_elevator') if answer.get('revision') == revision else None
        if type(uses_elevator) is not bool:
            uses_elevator = None
        subtotal = fee if uses_elevator else Decimal(0)
        percent = getattr(card, location + '_discount_percent')
        discount = (subtotal * percent / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amount = subtotal - discount
        locations.append({'location': location, 'address': address, 'revision': revision, 'uses_elevator': uses_elevator,
                          'subtotal': float(subtotal), 'discount_percent': float(percent), 'discount_amount': float(discount), 'total': float(amount),
                          'question': f'Will the movers need to use an elevator at {location}?',
                          'description': f'Elevator at {location}; {volume} cu ft. ${card.lower_fee:.2f} through {card.threshold_cuft} cu ft; ${card.upper_fee:.2f} above {card.threshold_cuft} cu ft.'})
    return {'threshold_cuft': card.threshold_cuft, 'lower_fee': float(card.lower_fee), 'upper_fee': float(card.upper_fee),
            'cubic_feet': volume, 'fee': float(fee), 'locations': locations,
            'total': float(sum(Decimal(str(row['total'])) for row in locations))}
