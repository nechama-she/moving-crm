"""Lead-list overview, using the same Priority 1 quote definition as Stats."""
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from models import Lead, LeadJob


def amount(raw):
    try:
        value = json.loads(raw or '{}').get('finalTotal') or 0
        result = Decimal(str(value))
        return result if result.is_finite() else Decimal(0)
    except (ValueError, TypeError, AttributeError, InvalidOperation):
        return Decimal(0)


def created_date(row, zone):
    raw = str(row.created_time or '').strip()
    try:
        if raw.replace('.', '', 1).isdigit():
            timestamp = float(raw)
            value = datetime.fromtimestamp(timestamp / 1000 if timestamp >= 1e12 else timestamp, timezone.utc)
        else:
            value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (ValueError, OverflowError, OSError):
        value = row.created_at
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(zone).date()


def overview(query, db, now=None):
    zone = ZoneInfo('America/New_York')
    today = (now or datetime.now(zone)).astimezone(zone).date()
    start = today.replace(day=1)
    result = dict(new_today=0, quotes=0, quote_value=Decimal(0), booked_value=Decimal(0))
    for row in query.with_entities(Lead.created_time, Lead.created_at, Lead.priority, Lead.estimated_total).yield_per(1000):
        created = created_date(row, zone)
        if created == today:
            result['new_today'] += 1
        if created and start <= created <= today and row.priority == 1:
            result['quotes'] += 1
            result['quote_value'] += amount(row.estimated_total)
    booked = query.join(LeadJob, LeadJob.lead_id == Lead.id).filter(
        LeadJob.job_order == 1, LeadJob.booked_move_date >= start,
        LeadJob.booked_move_date <= today,
        Lead.status.in_(['booked', 'scheduled', 'completed']))
    for row in booked.with_entities(Lead.estimated_total).yield_per(1000):
        result['booked_value'] += amount(row.estimated_total)
    return {key: float(value) if isinstance(value, Decimal) else value for key, value in result.items()}
