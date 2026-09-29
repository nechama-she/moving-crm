"""Admin maintenance of the shared inventory catalog."""
from decimal import Decimal
from uuid import uuid4
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import InventoryCatalogItem, User, PricingPlan
from long_distance_packing import packing_card

router = APIRouter(prefix='/api/inventory-catalog', tags=['Inventory catalog'])


class CatalogMaterial(BaseModel):
    plan_id: str = Field(min_length=1, max_length=36)
    material_id: str = Field(min_length=1, max_length=100)
    requirement: Literal['required', 'optional']
    quantity: Decimal = Field(gt=0, le=10000, decimal_places=2, allow_inf_nan=False)


class CatalogItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default='', max_length=2000)
    cuft: Decimal = Field(gt=0, le=10000, decimal_places=2, allow_inf_nan=False)
    weight: Decimal = Field(ge=0, le=1000000, decimal_places=2, allow_inf_nan=False)
    active: bool = True
    packing_materials: list[CatalogMaterial] = Field(default_factory=list, max_length=100)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Enter an item name')
        return value


def item_dict(item):
    return {'id': item.id, 'name': item.name, 'description': item.description,
            'cuft': float(item.cuft), 'weight': float(item.weight), 'active': item.active,
            'packing_materials': json.loads(item.packing_materials or '[]')}


@router.get('/material-options')
def material_options(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    options = []
    for plan in db.query(PricingPlan).order_by(PricingPlan.name).all():
        card = packing_card(plan.services)
        if card:
            options.extend({'plan_id': plan.id, 'plan_name': plan.name,
                            'material_id': row.id, 'name': row.name}
                           for row in card.materials)
    return {'items': options}


def item_values(body, db, existing=None):
    values = body.model_dump(exclude={'packing_materials'})
    if existing is not None and 'packing_materials' not in body.model_fields_set:
        return values
    old = {(row['plan_id'], row['material_id']) for row in json.loads(existing.packing_materials or '[]')} if existing else set()
    available = {(row['plan_id'], row['material_id']) for row in material_options(None, db)['items']} if body.packing_materials else set()
    seen = set()
    for row in body.packing_materials:
        key = (row.plan_id, row.material_id)
        if key in seen:
            raise HTTPException(422, 'Choose each material only once per pricing book')
        if key not in available and key not in old:
            raise HTTPException(422, 'Selected material is no longer available')
        seen.add(key)
    values['packing_materials'] = json.dumps([row.model_dump(mode='json') for row in body.packing_materials])
    return values


@router.get('')
def list_items(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {'items': [item_dict(item) for item in db.query(InventoryCatalogItem)
                     .order_by(InventoryCatalogItem.name, InventoryCatalogItem.cuft).all()]}


@router.post('', status_code=201)
def create_item(body: CatalogItemInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = InventoryCatalogItem(id=str(uuid4()), **item_values(body, db))
    db.add(item)
    db.commit()
    db.refresh(item)
    return item_dict(item)


@router.put('/{item_id}')
def update_item(item_id: str, body: CatalogItemInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(InventoryCatalogItem).filter_by(id=item_id).with_for_update().first()
    if not item:
        raise HTTPException(404, 'Catalog item not found')
    for key, value in item_values(body, db, item).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item_dict(item)
