"""Lead-list overview, using the same Priority 1 quote definition as Stats."""
import json
from datetime import date, datetime, timezone, timedelta
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


def previous_period(start, end):
    """The same days one month earlier, e.g. Oct 1-8 -> Sep 1-8 (capped at the end of that month)."""
    prev_start = date(start.year - (start.month == 1), (start.month - 2) % 12 + 1, 1)
    return prev_start, min(prev_start + (end - start), start - timedelta(days=1))


def overview(query, db, now=None, month=None):
    zone = ZoneInfo('America/New_York')
    today = (now or datetime.now(zone)).astimezone(zone).date()
    start = date.fromisoformat(month + "-01") if month else today.replace(day=1)
    next_month = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    end = min(today, next_month - timedelta(days=1))
    prev_start, prev_end = previous_period(start, end)
    last_week = today - timedelta(days=7)
    days = max((end - start).days + 1, 0)

    result = dict(new_today=0, new_month=0, quotes=0, quote_value=Decimal(0), booked_value=Decimal(0))
    # Comparison figures and a daily series for the overview cards' trend lines.
    previous = dict(new_today=0, new_month=0, quotes=0, quote_value=Decimal(0), booked_value=Decimal(0))
    trend = {key: [Decimal(0)] * days for key in ('new_leads', 'quotes', 'quote_value', 'booked_value')}

    for row in query.with_entities(Lead.created_time, Lead.created_at, Lead.priority, Lead.estimated_total).yield_per(1000):
        created = created_date(row, zone)
        if created == today:
            result['new_today'] += 1
        if created == last_week:
            previous['new_today'] += 1
        if created and start <= created <= end:
            day = (created - start).days
            result['new_month'] += 1
            trend['new_leads'][day] += 1
            if row.priority == 1:
                value = amount(row.estimated_total)
                result['quotes'] += 1
                result['quote_value'] += value
                trend['quotes'][day] += 1
                trend['quote_value'][day] += value
        elif created and prev_start <= created <= prev_end:
            previous['new_month'] += 1
            if row.priority == 1:
                previous['quotes'] += 1
                previous['quote_value'] += amount(row.estimated_total)

    booked = query.join(LeadJob, LeadJob.lead_id == Lead.id).filter(
        LeadJob.job_order == 1, LeadJob.booked_move_date >= prev_start,
        LeadJob.booked_move_date <= end,
        Lead.status.in_(['booked', 'scheduled', 'completed']))
    for row in booked.with_entities(Lead.estimated_total, LeadJob.booked_move_date).yield_per(1000):
        moved = row.booked_move_date.date() if isinstance(row.booked_move_date, datetime) else row.booked_move_date
        value = amount(row.estimated_total)
        if start <= moved <= end:
            result['booked_value'] += value
            trend['booked_value'][(moved - start).days] += value
        elif prev_start <= moved <= prev_end:
            previous['booked_value'] += value

    plain = lambda values: {key: float(value) if isinstance(value, Decimal) else value for key, value in values.items()}
    return {
        **plain(result),
        'previous': plain(previous),
        'trend': {key: [float(value) for value in series] for key, series in trend.items()},
    }
