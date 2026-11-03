"""Bulky item rates (handling, packing, crating), one row per item in pricing_bulky_items."""
import json
import re
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import HTTPException

BULKY_ITEM_MARKER = "__bulky_item__"
BULKY_ITEM_PREFIX = f"{BULKY_ITEM_MARKER}:"
PRICE_KEYS = ('handling', 'packing', 'crating')


def is_bulky_row(row):
    return row.comments == BULKY_ITEM_MARKER or row.comments.startswith(BULKY_ITEM_PREFIX)


def row_prices(row):
    """Prices as the API sends them: JSON in comments, with rate_text as the older handling price."""
    if row.comments.startswith(BULKY_ITEM_PREFIX):
        try:
            data = json.loads(row.comments[len(BULKY_ITEM_PREFIX):])
            if isinstance(data, dict):
                return {'handling': str(data.get('handling') or row.rate_text or ''),
                        'packing': str(data.get('packing') or ''), 'crating': str(data.get('crating') or '')}
        except (TypeError, ValueError):
            pass
    return {'handling': row.rate_text or '', 'packing': '', 'crating': ''}


def price_value(text):
    """A typed price as a number; blank means not offered."""
    cleaned = re.sub(r'[\s$,]', '', str(text or ''))
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f'Enter bulky item prices as numbers, not "{text}".')
    if value < 0 or not value.is_finite():
        raise ValueError(f'Enter bulky item prices as numbers, not "{text}".')
    return value


def item_prices(item):
    """The item's prices as text, the same shape row_prices returns."""
    return {key: '' if getattr(item, key) is None else format(getattr(item, key).normalize(), 'f') for key in PRICE_KEYS}


def bulky_service_rows(plan):
    """The items as the pricing API presents them: service rows holding their prices."""
    rows = []
    for item in plan.bulky_items:
        prices = item_prices(item)
        rows.append({'id': item.id, 'name': item.name, 'rate_text': prices['handling'],
                     'comments': BULKY_ITEM_PREFIX + json.dumps(prices), 'sort_order': item.sort_order})
    return rows


def save_bulky_items(plan, rows, first_sort_order=0):
    """Replace the plan's items with the incoming service rows, keeping each existing item's id."""
    from models import PricingBulkyItem
    existing = {item.id: item for item in plan.bulky_items}
    saved = []
    for position, row in enumerate(rows):
        row_id = getattr(row, 'id', None)
        if row_id and row_id not in existing:
            raise HTTPException(409, 'Pricing rows changed. Refresh the pricing book before saving.')
        item = existing.get(row_id) or PricingBulkyItem(id=str(uuid4()))
        item.name = row.name.strip()
        try:
            prices = {key: price_value(value) for key, value in row_prices(row).items()}
        except ValueError as error:
            raise HTTPException(422, str(error))
        for key, value in prices.items():
            setattr(item, key, value)
        item.sort_order = first_sort_order + position
        saved.append(item)
    plan.bulky_items[:] = saved


def migrate_bulky_items(connection):
    """Move each bulky item's pricing_services row into pricing_bulky_items with the same id, once."""
    from sqlalchemy import inspect, text
    from types import SimpleNamespace
    from models import PricingBulkyItem
    if inspect(connection).has_table(PricingBulkyItem.__tablename__):
        return 0
    PricingBulkyItem.__table__.create(connection)
    rows = connection.execute(text(
        "SELECT id, plan_id, name, rate_text, comments, sort_order FROM pricing_services "
        "WHERE comments = :marker OR comments LIKE :prefix"),
        {'marker': BULKY_ITEM_MARKER, 'prefix': BULKY_ITEM_PREFIX + '%'}).all()
    for row in rows:
        prices = row_prices(SimpleNamespace(rate_text=row.rate_text, comments=row.comments))
        connection.execute(PricingBulkyItem.__table__.insert().values(
            id=row.id, plan_id=row.plan_id, name=row.name, sort_order=row.sort_order,
            **{key: price_value(value) for key, value in prices.items()}))
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': row.id})
    return len(rows)
