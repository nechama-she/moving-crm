"""Pricing-book-owned catalog material requirements."""
import json
import re
from collections import Counter, defaultdict
from uuid import uuid5, NAMESPACE_URL
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


class DefaultMaterial(BaseModel):
    material_id: str = Field(min_length=1, max_length=100)
    requirement: Literal['required', 'optional']
    quantity: Decimal = Field(gt=0, le=10000, decimal_places=2, allow_inf_nan=False)


class ItemMaterialsInput(BaseModel):
    rows: list[ItemMaterial] = Field(max_length=10000)
    defaults: list[DefaultMaterial] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_rows(self):
        keys = [(row.item_id, row.material_id) for row in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError('Choose each material once per item')
        default_keys = [row.material_id for row in self.defaults]
        if len(default_keys) != len(set(default_keys)):
            raise ValueError('Choose each default material only once')
        return self


def material_configuration(plan):
    saved = json.loads(getattr(plan, 'item_materials', None) or '[]')
    return saved if isinstance(saved, dict) else {'rows': saved, 'defaults': []}


def material_assignments(plan, db):
    return material_configuration(plan).get('rows', [])


def default_materials(plan, db):
    return material_configuration(plan).get('defaults', [])


def sized_optional_defaults(defaults, rates, volume):
    """Offer the smallest fitting optional size within each material family."""
    result = []
    selected = {}
    for assignment in defaults:
        rate = rates.get(assignment['material_id'])
        capacity = (rate.capacity or rate.box_capacity_cuft) if rate else None
        if assignment['requirement'] != 'optional' or not rate or rate.capacity_unit != 'cuft' or capacity is None:
            result.append(assignment)
            continue
        if volume is None or not volume.is_finite() or volume <= 0:
            continue
        if (volume > capacity if rate.capacity_kind == 'over' else volume <= capacity):
            name = ' '.join(rate.name.casefold().split())
            family = next((family for family in ('carton crate', 'shrink wrap', 'mirror box', 'picture box', 'bubble corrugated wrap')
                           if re.search(r'\b' + family + r'\b', name)), name)
            rank = (Decimal('Infinity'), -capacity) if rate.capacity_kind == 'over' else (capacity, Decimal(0))
            if family not in selected or rank < selected[family][0]:
                selected[family] = (rank, assignment)
    chosen = {id(assignment) for _, assignment in selected.values()} | {id(assignment) for assignment in result}
    return [assignment for assignment in defaults if id(assignment) in chosen]


def material_setup(plan, db):
    card = packing_card(plan.services)
    items = [{'id': item.id, 'name': item.name, 'active': item.active}
             for item in db.query(InventoryCatalogItem).filter_by(deleted=False).order_by(InventoryCatalogItem.name).all()]
    valid = {item['id'] for item in items}
    configured = {row['item_id'] for row in material_assignments(plan, db)}
    return {'rows': [row for row in material_assignments(plan, db) if row['item_id'] in valid], 'defaults': default_materials(plan, db),
            'protection_review': [row for row in material_configuration(plan).get('protection_review', []) if row['item_id'] not in configured and row['item_id'] in valid],
            'items': items,
            'materials': [{'id': row.id, 'name': row.name} for row in card.materials] if card else []}


def save_material_assignments(plan, body, db):
    setup = material_setup(plan, db)
    old = {(row['item_id'], row['material_id']) for row in setup['rows']}
    old_defaults = {row['material_id'] for row in setup['defaults']}
    items = {row['id'] for row in setup['items']}
    materials = {row['id'] for row in setup['materials']}
    for row in body.rows:
        if (row.item_id, row.material_id) not in old and (row.item_id not in items or row.material_id not in materials):
            raise HTTPException(422, 'Choose an existing catalog item and a material from this pricing book')
    for row in body.defaults:
        if row.material_id not in materials and row.material_id not in old_defaults:
            raise HTTPException(422, 'Choose a default material from this pricing book')
    plan.item_materials = json.dumps({
        **material_configuration(plan),
        'rows': [row.model_dump(mode='json') for row in body.rows],
        'defaults': [row.model_dump(mode='json') for row in body.defaults],
    })
    db.commit()
    return material_setup(plan, db)


def customer_item_materials(plan, inventory, db):
    assignments = material_assignments(plan, db)
    defaults = default_materials(plan, db)
    if not assignments and not defaults:
        return [], set()
    card = packing_card(plan.services)
    rates = {row.id: row for row in card.materials} if card else {}
    catalog = db.query(InventoryCatalogItem).all()
    catalog_by_id = {item.id: item for item in catalog}
    def key(name):
        return ' '.join(sorted(re.findall(r'\w+', str(name).casefold())))
    by_name = defaultdict(list)
    for item in catalog:
        if not getattr(item, 'deleted', False):
            by_name[key(item.name)].append(item.id)
    by_item = defaultdict(list)
    for assignment in assignments:
        by_item[assignment['item_id']].append(assignment)
    result, matched = [], set()
    occurrences = Counter()
    for row in inventory:
        if not isinstance(row, dict) or row.get('going') is False:
            continue
        item_id = row.get('item_id')
        if not item_id:
            candidates = by_name[key(row.get('name', ''))]
            item_id = candidates[0] if len(candidates) == 1 else None
        item_assignments = by_item.get(item_id)
        if not item_assignments:
            if re.search(r'\bbox(?:es)?\b', str(row.get('name') or ''), re.IGNORECASE):
                continue
            count = max(1, int(row.get('amount') or row.get('quantity') or 1))
            try:
                volume = row.get('unit_cuft')
                if volume is None and row.get('cuft') is not None:
                    volume = Decimal(str(row['cuft'])) / count
                if volume is None:
                    volume = getattr(catalog_by_id.get(item_id), 'cuft', None)
                volume = Decimal(str(volume)) if volume is not None else None
            except (ValueError, TypeError, ArithmeticError):
                volume = None
            item_assignments = sized_optional_defaults(defaults, rates, volume)
        if not item_assignments:
            continue
        matched.add(key(row.get('name', '')))
        room = str(row.get('room') or '')
        count = max(1, int(row.get('amount') or row.get('quantity') or 1))
        for _ in range(count):
            occurrences[(item_id, room)] += 1
            unit = occurrences[(item_id, room)]
            group_identity = json.dumps([plan.id, item_id or key(row.get('name', '')), room, unit])
            group_id = 'configured-item:' + str(uuid5(NAMESPACE_URL, group_identity))
            for assignment in item_assignments:
                rate = rates.get(assignment['material_id'])
                quantity = Decimal(str(assignment['quantity']))
                labor = (rate.packing_price * quantity).quantize(Decimal('0.01')) if rate else Decimal(0)
                material = (rate.material_price * quantity).quantize(Decimal('0.01')) if rate else Decimal(0)
                material_row = {'id': assignment['material_id'],
                                'name': rate.name if rate else 'Unavailable material',
                                'quantity': float(quantity)}
                identity = json.dumps([plan.id, item_id or key(row.get('name', '')), room, unit,
                                       assignment['requirement'], assignment['material_id']])
                configured = {'id': 'configured:' + str(uuid5(NAMESPACE_URL, identity)),
                               'group_id': group_id,
                               'label': str(row.get('name') or 'Item') + (f' ({unit})' if count > 1 else ''),
                               'room': room, 'requirement': assignment['requirement'],
                               'material_name': material_row['name'],
                               'materials': [material_row],
                               'quantity': material_row['quantity'],
                               'available': rate is not None,
                               'price': float(labor + material), 'labor_price': float(labor),
                               'material_price': float(material)}
                result.append(configured)
    return result, matched
