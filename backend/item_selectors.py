"""Pricing-sheet-owned selectors for catalog items."""
import json
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from models import InventoryCatalogItem, Lead, LeadJob


class ItemSelector(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    item_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    options: list[str] = Field(min_length=1, max_length=50)

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
        if len({s.id for s in rows}) != len(rows) or len({(s.item_id, s.label.casefold()) for s in rows}) != len(rows):
            raise ValueError('Each selector needs a unique ID and a unique name for its item')
        if any(sum(s.item_id == row.item_id for s in rows) > 30 for row in rows):
            raise ValueError('Use at most 30 selectors per item')
        return rows


def selector_setup(plan, db):
    return {'rows': json.loads(plan.item_selectors or '[]'), 'items': [
        {'id': item.id, 'name': item.name, 'cuft': float(item.cuft)} for item in
        db.query(InventoryCatalogItem).filter_by(deleted=False).order_by(InventoryCatalogItem.name).all()]}


def save_selectors(plan, body, db):
    available = {item['id'] for item in selector_setup(plan, db)['items']}
    existing = {row['item_id'] for row in json.loads(plan.item_selectors or '[]')}
    if any(row.item_id not in available | existing for row in body.rows):
        raise HTTPException(422, 'Select an available catalog item')
    plan.item_selectors = json.dumps([row.model_dump() for row in body.rows])
    db.commit()
    return selector_setup(plan, db)


def inventory_selectors(access, db):
    lead, job = db.get(Lead, access.lead_id), db.get(LeadJob, access.job_id)
    if not (job.company_id or lead.company_id):
        return {}
    from routes.pricing import infer_job_move_type
    _, plan = infer_job_move_type(lead, job, db)
    result = {}
    for row in json.loads(getattr(plan, 'item_selectors', None) or '[]'):
        result.setdefault(row['item_id'], []).append(row)
    return result
