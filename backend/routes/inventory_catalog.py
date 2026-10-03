"""Admin maintenance of the shared inventory catalog."""
from decimal import Decimal
from uuid import uuid4
import json
import csv
import io
import re
import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, ValidationError
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import InventoryCatalogItem, User, PricingPlan
from long_distance_packing import packing_card

router = APIRouter(prefix='/api/inventory-catalog', tags=['Inventory catalog'])


def strip_hidden_csv_characters(value):
    # Keep language-significant joiners and visible Unicode characters intact.
    return value.translate(dict.fromkeys(map(ord, '\u200b\ufeff\u2060')))


def duplicate_key(name, cuft):
    name = unicodedata.normalize('NFKC', strip_hidden_csv_characters(name)).casefold()
    name = re.sub(r'\s*([^\w\s])\s*', r'\1', ' '.join(name.split()))
    return name, Decimal(cuft)


def available_items(db):
    return db.query(InventoryCatalogItem).filter_by(deleted=False)


def reject_duplicate(db, body, item_id=None):
    key = duplicate_key(body.name, body.cuft)
    if any(item.id != item_id and duplicate_key(item.name, item.cuft) == key
           for item in available_items(db).all()):
        raise HTTPException(409, 'This item already exists with the same volume. Edit the existing item instead.')


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
        value = ' '.join(strip_hidden_csv_characters(value).split())
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
    return {'items': [item_dict(item) for item in available_items(db)
                     .order_by(InventoryCatalogItem.name, InventoryCatalogItem.cuft).all()]}


@router.post('', status_code=201)
def create_item(body: CatalogItemInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    reject_duplicate(db, body)
    item = InventoryCatalogItem(id=str(uuid4()), **item_values(body, db))
    db.add(item)
    db.commit()
    db.refresh(item)
    return item_dict(item)


CSV_FIELDS = ['id', 'name', 'description', 'cuft', 'weight', 'active', 'packing_materials']
MAX_CSV_BYTES = 10 * 1024 * 1024


@router.get('/export')
def export_items(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for item in available_items(db).order_by(InventoryCatalogItem.name, InventoryCatalogItem.cuft).all():
        row = item_dict(item)
        row['packing_materials'] = json.dumps(row['packing_materials'])
        # Escape spreadsheet formulas while preserving text on re-import.
        for key in ('name', 'description'):
            if row[key] and row[key].startswith(('=', '+', '-', '@', '\t', '\r', '\n', "'")):
                row[key] = "'" + row[key]
        writer.writerow(row)
    return Response(content=output.getvalue().encode('utf-8-sig'), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="inventory-catalog.csv"'})


@router.post('/import')
async def import_items(file: UploadFile = File(...), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(413, 'CSV file must be 10 MB or smaller')
    try:
        if data.startswith((b'\xff\xfe', b'\xfe\xff')):
            content = data.decode('utf-16')
        else:
            try:
                content = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                content = data.decode('cp1252')
        reader = csv.DictReader(io.StringIO(content, newline=''), strict=True)
        fields = [strip_hidden_csv_characters(field).strip().lower() for field in (reader.fieldnames or [])]
        reader.fieldnames = fields
        if len(fields) != len(set(fields)) or not {'name', 'cuft', 'weight'}.issubset(fields) or set(fields) - set(CSV_FIELDS):
            raise HTTPException(422, 'CSV needs name, cuft, weight columns. Optional columns: id, description, active, packing_materials.')
        existing = {item.id: item for item in available_items(db).order_by(InventoryCatalogItem.active.desc(), InventoryCatalogItem.id).with_for_update().all()}
        by_name = {}
        for item in existing.values():
            by_name.setdefault(duplicate_key(item.name, item.cuft), item)
        pending, seen, staged = [], set(), {}
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise HTTPException(422, f'Row {line}: column count does not match the header')
            item_id = row.pop('id', '').strip()
            if item_id and (item_id not in existing or item_id in seen):
                raise HTTPException(422, f'Row {line}: unknown or duplicate item ID. Leave ID blank for new items.')
            seen.add(item_id)
            item = existing.get(item_id)
            for key in ('name', 'description'):
                if row.get(key, '').startswith(("'=", "'+", "'-", "'@", "'\t", "'\r", "'\n", "''")):
                    row[key] = row[key][1:]
            if 'packing_materials' in row:
                try:
                    row['packing_materials'] = json.loads(row['packing_materials'] or '[]')
                except ValueError:
                    raise HTTPException(422, f'Row {line}: packing_materials must be a JSON list')
            try:
                body = CatalogItemInput(**row)
                key = duplicate_key(body.name, body.cuft)
                if not item_id:
                    item = by_name.get(key)
                elif key in by_name and by_name[key].id != item_id and duplicate_key(item.name, item.cuft) != key:
                    raise HTTPException(409, 'This name and volume already belong to another catalog item.')
                if item is not None:
                    for field in ('description', 'active'):
                        if field not in row:
                            row[field] = getattr(item, field)
                    body = CatalogItemInput(**row)
                values = item_values(body, db, item)
                if key in staged:
                    previous = staged[key]
                    if {k: v for k, v in values.items() if k != 'name'} != {k: v for k, v in previous.items() if k != 'name'}:
                        raise HTTPException(422, 'Duplicate item has conflicting values. Keep one row for each item and volume.')
                    continue
                staged[key] = values
            except ValidationError as exc:
                error = exc.errors()[0]
                raise HTTPException(422, f"Row {line}: {'.'.join(map(str, error['loc']))}: {error['msg']}")
            except HTTPException as exc:
                raise HTTPException(422, f'Row {line}: {exc.detail}')
            pending.append((item, values))
    except UnicodeDecodeError:
        raise HTTPException(422, 'Could not read this file. Upload a CSV saved from your spreadsheet.')
    except csv.Error:
        raise HTTPException(422, 'The CSV has malformed quotes or rows. Save it again as CSV from your spreadsheet and retry.')
    if not pending:
        raise HTTPException(422, 'CSV has no items to import')
    created = sum(item is None for item, _ in pending)
    for item, values in pending:
        if item is None:
            db.add(InventoryCatalogItem(id=str(uuid4()), **values))
        else:
            for key, value in values.items():
                setattr(item, key, value)
    db.commit()
    return {'created': created, 'updated': len(pending) - created}


@router.put('/{item_id}')
def update_item(item_id: str, body: CatalogItemInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = available_items(db).filter_by(id=item_id).with_for_update().first()
    if not item:
        raise HTTPException(404, 'Catalog item not found')
    if duplicate_key(item.name, item.cuft) != duplicate_key(body.name, body.cuft):
        reject_duplicate(db, body, item_id)
    for key, value in item_values(body, db, item).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item_dict(item)


@router.delete('/{item_id}')
def delete_item(item_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = available_items(db).filter_by(id=item_id).with_for_update().first()
    if not item:
        raise HTTPException(404, 'Catalog item not found')
    # Retain the record for saved inventory and moving-term references.
    item.deleted = True
    db.commit()
    return {'deleted': True}


@router.post('/deduplicate')
def deduplicate_items(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    seen, removed = set(), 0
    for item in available_items(db).order_by(InventoryCatalogItem.cuft.desc(), InventoryCatalogItem.active.desc(), InventoryCatalogItem.id).with_for_update().all():
        key = duplicate_key(item.name, item.cuft)[0]
        if key in seen:
            item.deleted = True
            removed += 1
        else:
            seen.add(key)
    db.commit()
    return {'removed': removed}
