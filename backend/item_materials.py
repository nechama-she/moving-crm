"""Pricing-book-owned catalog material requirements."""
import json
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from models import InventoryCatalogItem
from long_distance_packing import packing_card


class ItemMaterial(BaseModel):
    item_id: str = Field(min_length=1, max_length=36)
    material_id: str = Field(min_length=1, max_length=100)
    requirement: Literal['required', 'optional']
    quantity: Decimal = Field(gt=0, le=10000, decimal_places=2, allow_inf_nan=False)


class ItemMaterialsInput(BaseModel):
    rows: list[ItemMaterial] = Field(max_length=10000)

    @model_validator(mode='after')
    def unique_rows(self):
        keys = [(row.item_id, row.material_id) for row in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError('Choose each material once per item')
        return self


def material_assignments(plan, db):
    return json.loads(plan.item_materials or '[]')


def material_setup(plan, db):
    card = packing_card(plan.services)
    return {'rows': material_assignments(plan, db),
            'items': [{'id': item.id, 'name': item.name, 'active': item.active}
                      for item in db.query(InventoryCatalogItem).order_by(InventoryCatalogItem.name).all()],
            'materials': [{'id': row.id, 'name': row.name} for row in card.materials] if card else []}


def save_material_assignments(plan, body, db):
    setup = material_setup(plan, db)
    old = {(row['item_id'], row['material_id']) for row in setup['rows']}
    items = {row['id'] for row in setup['items']}
    materials = {row['id'] for row in setup['materials']}
    for row in body.rows:
        if (row.item_id, row.material_id) not in old and (row.item_id not in items or row.material_id not in materials):
            raise HTTPException(422, 'Choose an existing catalog item and a material from this pricing book')
    plan.item_materials = json.dumps([row.model_dump(mode='json') for row in body.rows])
    db.commit()
    return material_setup(plan, db)
