"""Pricing-sheet-owned selectors for catalog items."""
import json
from decimal import Decimal
from typing import Annotated
from uuid import uuid5, NAMESPACE_URL
from charge_errors import isolated_charge
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from models import InventoryCatalogItem, Lead, LeadJob


class ItemSelector(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    item_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=10000)
    label: str = Field(default='Service', min_length=1, max_length=200)
    options: list[str] = Field(min_length=1, max_length=50)
    default: str | None = Field(default=None, max_length=200)
    prices: list[Annotated[Decimal, Field(ge=0, le=1000000, decimal_places=2, allow_inf_nan=False)] | None] = Field(default_factory=list, max_length=50)

    @model_validator(mode='before')
    @classmethod
    def legacy_item(cls, value):
        if isinstance(value, dict) and 'item_ids' not in value:
            value = {**value, 'item_ids': [value['item_id']] if value.get('item_id') else []}
        return value

    @model_validator(mode='after')
    def valid_default(self):
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError('Attach each item only once')
        if self.default is None:
            self.default = self.options[0]
        if self.default not in self.options:
            raise ValueError('Choose a default from the service options')
        if self.prices and len(self.prices) != len(self.options):
            raise ValueError('Provide one optional price per option')
        if not self.prices:
            self.prices = [None] * len(self.options)
        return self

    @field_validator('label')
    @classmethod
    def clean_label(cls, value):
        if not value.strip():
            raise ValueError('Enter a selector name')
        return value.strip()

    @field_validator('options')
    @classmethod
    def clean_options(cls, values):
        values = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in values) or len({v.casefold() for v in values}) != len(values):
            raise ValueError('Options must be unique, nonempty labels of up to 200 characters')
        return values


class ItemSelectorsInput(BaseModel):
    rows: list[ItemSelector] = Field(max_length=1000)

    @field_validator('rows')
    @classmethod
    def unique_selectors(cls, rows):
        if len({s.id for s in rows}) != len(rows):
            raise ValueError('Each selector needs a unique ID')
        from collections import Counter
        if any(count > 30 for count in Counter(item for row in rows for item in row.item_ids).values()):
            raise ValueError('Use at most 30 selectors per item')
        return rows


def service_rows(plan):
    return [{**row, 'item_ids': row.get('item_ids', [row['item_id']] if row.get('item_id') else [])}
            for row in json.loads(getattr(plan, 'item_selectors', None) or '[]')]


def selector_setup(plan, db):
    return {'rows': service_rows(plan), 'items': [
        {'id': item.id, 'name': item.name, 'cuft': float(item.cuft)} for item in
        db.query(InventoryCatalogItem).filter_by(deleted=False).order_by(InventoryCatalogItem.name).all()]}


def save_selectors(plan, body, db):
    available = {item['id'] for item in selector_setup(plan, db)['items']}
    existing = {item for row in service_rows(plan) for item in row['item_ids']}
    if any(item not in available | existing for row in body.rows for item in row.item_ids):
        raise HTTPException(422, 'Select an available catalog item')
    plan.item_selectors = json.dumps([row.model_dump(mode='json') for row in body.rows])
    db.commit()
    return selector_setup(plan, db)


def inventory_selectors(access, db):
    lead, job = db.get(Lead, access.lead_id), db.get(LeadJob, access.job_id)
    if not (job.company_id or lead.company_id):
        return {}
    from routes.pricing import infer_job_move_type
    _, plan = infer_job_move_type(lead, job, db)
    result = {}
    for row in service_rows(plan):
        for item_id in row['item_ids']:
            result.setdefault(item_id, []).append(row)
    return result


@isolated_charge('Item services')
def add_service_charges(lead, job, db, plan):
    """Price current inventory choices once per unit, including configured defaults."""
    from models import LeadLiveSwitch, LeadJobCharge
    from inventory_edits import source
    from catalog_names import resolve_catalog_names
    definitions = {}
    for definition in service_rows(plan):
        for item_id in definition['item_ids']:
            definitions.setdefault(item_id, []).append(definition)
    if not definitions:
        return Decimal(0)
    saved = db.get(LeadLiveSwitch, lead.id)
    _, rows, _ = source(json.loads(saved.details or '{}') if saved else {})
    charges = {}
    for row in resolve_catalog_names(rows, db):
        if row.get('going') is False:
            continue
        item_id = row.get('catalog_item_id') or row.get('item_id')
        quantity = Decimal(str(row.get('amount') or 0))
        if quantity <= 0:
            continue
        for definition in definitions.get(item_id, []):
            options = definition['options']
            selected = (row.get('selections') or {}).get(definition['id']) or definition.get('default') or options[0]
            if selected not in options:
                raise ValueError(f"Review the saved service option for {row['name']}: {selected}")
            prices = definition.get('prices') or []
            index = options.index(selected)
            price = Decimal(str(prices[index] or 0)) if index < len(prices) else Decimal(0)
            if price <= 0:
                continue
            key = (item_id, definition['id'], selected)
            if key not in charges:
                charges[key] = {'name': row['name'], 'quantity': Decimal(0), 'price': price}
            charges[key]['quantity'] += quantity
    total = Decimal(0)
    for index, (key, charge) in enumerate(charges.items()):
        amount = (charge['quantity'] * charge['price']).quantize(Decimal('.01'))
        db.add(LeadJobCharge(
            id=str(uuid5(NAMESPACE_URL, f'item-service:{job.id}:{json.dumps(key)}')),
            job_id=job.id, name=f"{charge['name']} — {key[2]}",
            description=f"{charge['quantity']:g} items × ${charge['price']:.2f} per item",
            subtotal=amount, discount_amount=0, total_cost=amount, sort_order=3100+index))
        total += amount
    return total
