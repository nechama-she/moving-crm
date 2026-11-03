"""Storage charged by configured day periods after a free allowance."""
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field

STORAGE_PREFIX = '__storage_periods__:'


class StorageCard(BaseModel):
    enabled: bool = False
    free_days: int = Field(ge=0, le=36500)
    period_days: int = Field(gt=0, le=36500)
    rate_per_cuft: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    minimum_cubic_feet: int | None = Field(default=None, ge=0, le=1000000)


def storage_card(services):
    for service in services:
        if service.comments.startswith(STORAGE_PREFIX):
            return StorageCard.model_validate_json(service.comments[len(STORAGE_PREFIX):])
    return None


FIELDS = ('enabled', 'free_days', 'period_days', 'rate_per_cuft', 'minimum_cubic_feet')


def plan_storage_card(plan):
    """The plan's storage pricing, read from pricing_storage."""
    row = plan.storage
    if row is None:
        return None
    return StorageCard(**{field: getattr(row, field) for field in FIELDS})


def storage_service_row(plan):
    """The card as the pricing API presents it: a service row holding its settings."""
    card = plan_storage_card(plan)
    if card is None:
        return None
    config = {field: format(value.normalize(), 'f') if isinstance(value, Decimal) else value
              for field, value in card.model_dump().items()}
    return {'id': f'storage:{plan.id}', 'name': 'Storage pricing', 'rate_text': '',
            'comments': STORAGE_PREFIX + json.dumps(config), 'sort_order': -1}


def save_storage_card(plan, card):
    """Replace the plan's storage pricing; None removes it."""
    from models import PricingStorage
    if card is None:
        plan.storage = None
        return
    row = plan.storage or PricingStorage()
    for field in FIELDS:
        setattr(row, field, getattr(card, field))
    plan.storage = row


def migrate_storage_cards(connection):
    """Move each plan's card from its pricing_services JSON row into pricing_storage, once."""
    from sqlalchemy import inspect, text
    from models import PricingStorage
    if inspect(connection).has_table(PricingStorage.__tablename__):
        return 0
    PricingStorage.__table__.create(connection)
    moved = set()
    rows = connection.execute(text(
        "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
        {'prefix': STORAGE_PREFIX + '%'}).all()
    for service_id, plan_id, comments in rows:
        # Pricing used the first card of a plan; any later copies were never read.
        if plan_id not in moved:
            card = StorageCard.model_validate_json(comments[len(STORAGE_PREFIX):])
            connection.execute(PricingStorage.__table__.insert().values(
                plan_id=plan_id, **{field: getattr(card, field) for field in FIELDS}))
            moved.add(plan_id)
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)


def storage_quote(card, pickup_date, available_date, volume, move_minimum):
    if not card or not card.enabled:
        return None
    try:
        available = date.fromisoformat(available_date) if available_date else None
    except ValueError:
        available = None
    valid = bool(pickup_date and available and available >= pickup_date)
    elapsed = (available - pickup_date).days if valid else None
    paid_days = max(0, elapsed - card.free_days) if elapsed is not None else 0
    periods = (paid_days + card.period_days - 1) // card.period_days
    minimum = move_minimum if card.minimum_cubic_feet is None else card.minimum_cubic_feet
    billable = max(volume, minimum)
    total = (card.rate_per_cuft * billable * periods).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'question': 'What is the earliest date you can receive your shipment?',
            'pickup_date': pickup_date.isoformat() if pickup_date else '',
            'available_date': available.isoformat() if available else '', 'valid': valid,
            'free_days': card.free_days, 'period_days': card.period_days,
            'rate_per_cuft': float(card.rate_per_cuft), 'inventory_cubic_feet': volume,
            'minimum_cubic_feet': minimum, 'cubic_feet': billable, 'elapsed_days': elapsed,
            'paid_periods': periods, 'billed_days': periods * card.period_days, 'total': float(total),
            'description': f"{periods} paid period(s) of {card.period_days} days × {billable} cu ft × ${card.rate_per_cuft:.2f}; first {card.free_days} days free. Earliest receipt: {available_date or 'not answered'}."}
