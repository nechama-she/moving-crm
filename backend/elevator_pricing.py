"""Elevator charges, independently priced at each address."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field, model_validator

ELEVATOR_PREFIX = '__elevator_pricing__:'


class ElevatorTier(BaseModel):
    up_to_cuft: int | None = Field(default=None, gt=0, le=1000000)
    fee: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class ElevatorCard(BaseModel):
    enabled: bool = False
    tiers: list[ElevatorTier] = Field(min_length=1, max_length=100)

    @model_validator(mode='before')
    @classmethod
    def legacy_tiers(cls, value):
        if isinstance(value, dict) and 'tiers' not in value:
            value = {**value, 'tiers': [
                {'up_to_cuft': value.get('threshold_cuft'), 'fee': value.get('lower_fee')},
                {'up_to_cuft': None, 'fee': value.get('upper_fee')}]}
        return value

    @model_validator(mode='after')
    def ordered_tiers(self):
        limits = [tier.up_to_cuft for tier in self.tiers[:-1]]
        if self.tiers[-1].up_to_cuft is not None or any(limit is None for limit in limits):
            raise ValueError('The final tier must cover all volume above the last threshold')
        if limits != sorted(set(limits)):
            raise ValueError('Volume thresholds must increase without duplicates')
        return self

    pickup_discount_percent: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)
    delivery_discount_percent: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)


def elevator_card(services):
    for service in services:
        if service.comments.startswith(ELEVATOR_PREFIX):
            return ElevatorCard.model_validate_json(service.comments[len(ELEVATOR_PREFIX):])
    return None


def elevator_quote(card, addresses, saved, volume):
    if not card or not card.enabled:
        return None
    tier = next(t for t in card.tiers if t.up_to_cuft is None or volume <= t.up_to_cuft)
    fee = tier.fee
    terms = '; '.join(f'${t.fee:.2f} ' + (f'through {t.up_to_cuft} cu ft' if t.up_to_cuft is not None else (f'above {card.tiers[-2].up_to_cuft} cu ft' if len(card.tiers) > 1 else 'for all volumes')) for t in card.tiers)
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
                          'description': f'Elevator at {location}; {volume} cu ft. {terms}.'})
    return {'tiers': [{'up_to_cuft': t.up_to_cuft, 'fee': float(t.fee)} for t in card.tiers], 'terms': terms,
            'cubic_feet': volume, 'fee': float(fee), 'locations': locations,
            'total': float(sum(Decimal(str(row['total'])) for row in locations))}
