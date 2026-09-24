"""Storage charged by configured day periods after a free allowance."""
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
