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


def plan_elevator_card(plan):
    """The plan's elevator pricing, read from pricing_elevator and pricing_elevator_tiers."""
    row = plan.elevator
    if row is None:
        return None
    # Tiers by volume, with the open-ended tier last.
    tiers = sorted(row.tiers, key=lambda tier: (tier.up_to_cuft is None, tier.up_to_cuft or 0))
    return ElevatorCard(enabled=row.enabled, tiers=[ElevatorTier(up_to_cuft=tier.up_to_cuft, fee=tier.fee) for tier in tiers],
                        pickup_discount_percent=row.pickup_discount_percent,
                        delivery_discount_percent=row.delivery_discount_percent)


def elevator_service_row(plan):
    """The card as the pricing API presents it: a service row holding its settings."""
    card = plan_elevator_card(plan)
    if card is None:
        return None
    number = lambda value: format(value.normalize(), 'f')
    config = {'enabled': card.enabled,
              'tiers': [{'up_to_cuft': tier.up_to_cuft, 'fee': number(tier.fee)} for tier in card.tiers],
              'pickup_discount_percent': number(card.pickup_discount_percent),
              'delivery_discount_percent': number(card.delivery_discount_percent)}
    return {'id': f'elevator:{plan.id}', 'name': 'Elevator pricing', 'rate_text': '',
            'comments': ELEVATOR_PREFIX + json.dumps(config), 'sort_order': -1}


def save_elevator_card(plan, card):
    """Replace the plan's elevator pricing; None removes it."""
    from models import PricingElevator, PricingElevatorTier
    if card is None:
        plan.elevator = None
        return
    row = plan.elevator or PricingElevator()
    row.enabled = card.enabled
    row.pickup_discount_percent = card.pickup_discount_percent
    row.delivery_discount_percent = card.delivery_discount_percent
    # Keep unchanged tiers so the unique (plan_id, up_to_cuft) key never collides mid-save.
    existing = {tier.up_to_cuft: tier for tier in row.tiers}
    row.tiers[:] = [existing.get(tier.up_to_cuft) or PricingElevatorTier(up_to_cuft=tier.up_to_cuft) for tier in card.tiers]
    for saved, tier in zip(row.tiers, card.tiers):
        saved.fee = tier.fee
    plan.elevator = row


def migrate_elevator_cards(connection):
    """Move each plan's card from its pricing_services JSON row into the elevator tables, once."""
    from uuid import uuid4
    from sqlalchemy import inspect, text
    from models import PricingElevator, PricingElevatorTier
    if inspect(connection).has_table(PricingElevator.__tablename__):
        return 0
    PricingElevator.__table__.create(connection)
    PricingElevatorTier.__table__.create(connection)
    moved = set()
    rows = connection.execute(text(
        "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
        {'prefix': ELEVATOR_PREFIX + '%'}).all()
    for service_id, plan_id, comments in rows:
        # Pricing used the first card of a plan; any later copies were never read.
        if plan_id not in moved:
            card = ElevatorCard.model_validate_json(comments[len(ELEVATOR_PREFIX):])
            connection.execute(PricingElevator.__table__.insert().values(
                plan_id=plan_id, enabled=card.enabled,
                pickup_discount_percent=card.pickup_discount_percent,
                delivery_discount_percent=card.delivery_discount_percent))
            for tier in card.tiers:
                connection.execute(PricingElevatorTier.__table__.insert().values(
                    id=str(uuid4()), plan_id=plan_id, up_to_cuft=tier.up_to_cuft, fee=tier.fee))
            moved.add(plan_id)
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)


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
        unknown = answer.get('revision') == revision and answer.get('unknown') is True
        uses_elevator = answer.get('uses_elevator') if answer.get('revision') == revision else None
        if unknown or type(uses_elevator) is not bool:
            uses_elevator = None
        subtotal = fee if uses_elevator else Decimal(0)
        percent = getattr(card, location + '_discount_percent')
        discount = (subtotal * percent / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amount = subtotal - discount
        locations.append({'location': location, 'address': address, 'revision': revision, 'uses_elevator': uses_elevator, 'unknown': unknown,
                          'subtotal': float(subtotal), 'discount_percent': float(percent), 'discount_amount': float(discount), 'total': float(amount),
                          'question': f'Will the movers need to use an elevator at {location}?',
                          'description': f'Elevator at {location}; {volume} cu ft. {terms}.'})
    return {'tiers': [{'up_to_cuft': t.up_to_cuft, 'fee': float(t.fee)} for t in card.tiers], 'terms': terms,
            'cubic_feet': volume, 'fee': float(fee), 'locations': locations,
            'total': float(sum(Decimal(str(row['total'])) for row in locations))}
