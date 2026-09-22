"""Admin maintenance of the shared inventory catalog."""
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import InventoryCatalogItem, User

router = APIRouter(prefix='/api/inventory-catalog', tags=['Inventory catalog'])


class CatalogItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default='', max_length=2000)
    cuft: Decimal = Field(gt=0, le=10000, decimal_places=2, allow_inf_nan=False)
    weight: Decimal = Field(ge=0, le=1000000, decimal_places=2, allow_inf_nan=False)
    active: bool = True

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Enter an item name')
        return value


def item_dict(item):
    return {'id': item.id, 'name': item.name, 'description': item.description,
            'cuft': float(item.cuft), 'weight': float(item.weight), 'active': item.active}


@router.get('')
def list_items(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {'items': [item_dict(item) for item in db.query(InventoryCatalogItem)
                     .order_by(InventoryCatalogItem.name, InventoryCatalogItem.cuft).all()]}


@router.post('', status_code=201)
def create_item(body: CatalogItemInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = InventoryCatalogItem(id=str(uuid4()), **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item_dict(item)


@router.put('/{item_id}')
def update_item(item_id: str, body: CatalogItemInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(InventoryCatalogItem).filter_by(id=item_id).with_for_update().first()
    if not item:
        raise HTTPException(404, 'Catalog item not found')
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item_dict(item)
