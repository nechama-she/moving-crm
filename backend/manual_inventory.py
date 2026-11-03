"""Customer-entered room inventories use catalog values and the shared pricing flow."""
import json
import re
import time
from decimal import Decimal
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from models import InventoryRoomType, InventoryCatalogItem, LeadLiveSwitch, LeadJob
from spark_history import remember_report, REPORT_KEYS, CONVERSATION_KEYS
from item_selectors import ServiceSelections


class InventoryItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str
    quantity: int = Field(ge=1, le=999, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class CustomInventoryItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    catalog_item_id: str | None = None
    name_override: bool = False
    name: str = Field(min_length=1, max_length=200)
    cuft: Decimal = Field(gt=0, le=10000, allow_inf_nan=False)
    quantity: int = Field(ge=1, le=999, strict=True)
    mover_pack: bool | None = None
    mover_pack_count: int | None = Field(default=None, ge=0, le=999, strict=True)
    selections: ServiceSelections = Field(default_factory=dict)
    going: bool = True
    reference_name: str | None = Field(default=None, max_length=200)
    set_id: UUID | None = None
    set_name: str | None = Field(default=None, min_length=1, max_length=200)


class InventoryRoomInput(BaseModel):
    room_type_id: str
    name: str = Field(min_length=1, max_length=100)
    items: list[InventoryItemInput] = Field(max_length=500)
    custom_items: list[CustomInventoryItemInput] = Field(default_factory=list, max_length=100)


class ManualInventoryInput(BaseModel):
    request_id: UUID
    rooms: list[InventoryRoomInput] = Field(max_length=100)


def catalog_items(db, access, query):
    """Catalog items as the inventory window shows them, with this move's item services."""
    from item_selectors import inventory_selectors
    rows = query.all()
    selectors = inventory_selectors(access, db, {r.id for r in rows}) if access and rows else {}
    return [{'id': r.id, 'name': r.name, 'description': r.description,
             'cuft': float(r.cuft), 'weight': float(r.weight), 'selectors': selectors.get(r.id, [])} for r in rows]


def catalog(db, access=None):
    """Room types and sets. Items are searched on demand; only the sets' component items are included."""
    from models import InventoryCatalogSet
    sets = [{'id': row.id, 'name': row.name, 'components': json.loads(row.components)}
            for row in db.query(InventoryCatalogSet).order_by(InventoryCatalogSet.name).all()]
    component_ids = {part['item_id'] for row in sets for part in row['components']}
    return {'rooms': [{'id': r.id, 'name': r.name} for r in db.query(InventoryRoomType).order_by(InventoryRoomType.sort_order).all()],
            'sets': sets,
            'items': search_catalog(db, access, ids=component_ids) if component_ids else []}


def search_catalog(db, access, text='', ids=(), limit=50):
    """Up to `limit` items matching every word of `text` in their name or description, or the given ids."""
    from sqlalchemy import or_
    query = db.query(InventoryCatalogItem).filter(InventoryCatalogItem.active.is_(True), InventoryCatalogItem.deleted.is_(False))
    if ids:
        return catalog_items(db, access, query.filter(InventoryCatalogItem.id.in_(list(ids)[:200])))
    words = text.split()
    if not words:
        return []
    for word in words[:10]:
        # Typed % and _ match literally.
        pattern = '%' + word.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        query = query.filter(or_(InventoryCatalogItem.name.ilike(pattern, escape='!'),
                                 InventoryCatalogItem.description.ilike(pattern, escape='!')))
    return catalog_items(db, access, query.order_by(InventoryCatalogItem.name, InventoryCatalogItem.cuft).limit(limit))


def build_inventory(body, db, allow_empty=False):
    room_types = {r.id for r in db.query(InventoryRoomType).all()}
    ids = {item.item_id for room in body.rooms for item in room.items}
    items = {r.id: r for r in db.query(InventoryCatalogItem).filter(InventoryCatalogItem.id.in_(ids), InventoryCatalogItem.active.is_(True)).all()}
    linked_ids = {item.catalog_item_id for room in body.rooms for item in room.custom_items if item.catalog_item_id}
    linked = {item.id: item for item in db.query(InventoryCatalogItem).filter(InventoryCatalogItem.id.in_(linked_ids)).all()} if linked_ids else {}
    if (not ids and not any(room.custom_items for room in body.rooms) and not allow_empty) or set(items) != ids:
        raise HTTPException(400, 'Choose available items from the inventory list.')
    rows = []
    rooms = []
    cuft = weight = Decimal(0)
    for room in body.rooms:
        if room.room_type_id not in room_types or not room.name.strip():
            raise HTTPException(400, 'Choose a valid room type and name.')
        contents = []
        for entry in room.items:
            item = items[entry.item_id]
            if item.cuft <= 0 or item.weight < 0:
                raise HTTPException(409, 'An item needs its catalog measurements corrected.')
            volume = item.cuft * entry.quantity
            mass = item.weight * entry.quantity
            cuft += volume
            weight += mass
            display_name = entry.name.strip() if entry.name else item.name
            row = {'item_id': item.id, 'room': room.name.strip(), 'name': display_name, 'name_override': bool(entry.name),
                   'amount': entry.quantity, 'cuft': float(volume), 'weight': float(mass),
                   'unit_cuft': float(item.cuft), 'unit_weight': float(item.weight)}
            if display_name != item.name:
                row['reference_name'] = item.name
            rows.append(row)
            contents.append(row)
        for entry in room.custom_items:
            if not entry.name.strip():
                raise HTTPException(400, 'Enter a name for each custom item.')
            volume = entry.cuft * entry.quantity if entry.going else Decimal(0)
            cuft += volume
            catalog_item = linked.get(entry.catalog_item_id)
            display_name = entry.name.strip()
            if catalog_item and not entry.name_override:
                suffix = re.search(r'\s*\((?:CP|PBO)\)\s*$', display_name, re.I)
                display_name = catalog_item.name + (suffix.group(0) if suffix else '')
            row = {'item_id': catalog_item.id if catalog_item else 'custom-' + str(entry.id), 'room': room.name.strip(), 'name': display_name,
                   'catalog_item_id': catalog_item.id if catalog_item else None, 'name_override': entry.name_override,
                   'amount': entry.quantity, 'cuft': float(volume), 'weight': 0,
                   'unit_cuft': float(entry.cuft), 'unit_weight': 0, 'custom': True, 'going': entry.going, 'mover_pack': entry.mover_pack, 'mover_pack_count': entry.mover_pack_count,
                   'reference_name': entry.reference_name or entry.name.strip(), 'selections': entry.selections,
                   'set_id': str(entry.set_id) if entry.set_id else None, 'set_name': entry.set_name}
            rows.append(row)
            contents.append(row)
        rooms.append({'room_type_id': room.room_type_id, 'name': room.name.strip(), 'items': contents})
    from catalog_names import resolve_catalog_names
    resolved = resolve_catalog_names(rows, db)
    index = 0
    for room in rooms:
        count = len(room['items'])
        room['items'] = resolved[index:index + count]
        index += count
    return rooms, resolved, float(cuft), float(weight)


def submit_inventory_snapshot(list_body, rooms, rows, cuft, weight, access, db):
    from routes.liveswitch import apply_spark_results_to_lead
    job = db.query(LeadJob).filter_by(id=access.job_id).with_for_update().one()
    saved = db.get(LeadLiveSwitch, access.lead_id)
    details = json.loads(saved.details or '{}') if saved else {}
    report_id = 'manual-' + str(list_body['request_id'])
    if any(row.get('last_spark_id') == report_id for row in details.get('spark_history', [])):
        if details.get('last_spark_id') != report_id:
            raise HTTPException(409, 'This list is already in your history. Select it there.')
        return apply_spark_results_to_lead(access.lead_id, '', db, expected_report_id=report_id)
    details['report_customer_packing'] = job.customer_packing
    details['report_customer_package'] = job.customer_packing_package
    remember_report(details)
    details['carried_question_state'] = details.get('carried_question_state') or {key: details[key] for key in ('report_question_answers', 'question_original_rows', 'spark_inventory_snapshot') if key in details}
    for key in REPORT_KEYS:
        if key != 'carried_question_state':
            details.pop(key, None)
    details['report_customer_packing'] = job.customer_packing
    details['report_customer_package'] = job.customer_packing_package
    for key in CONVERSATION_KEYS:
        details[key] = ''
    details.update(last_spark_id=report_id, last_spark_status='completed', last_spark_at=int(time.time()),
                   report_list_body=list_body, report_source='manual', manual_rooms=rooms,
                   spark_inventory_snapshot=[dict(row, manual=True) for row in rows],
                   spark_extracted_cuft=cuft, spark_extracted_weight=weight, report_files=[],
                   report_conversation={}, spark_pricing_ready=False)
    remember_report(details)
    if not saved:
        saved = LeadLiveSwitch(lead_id=access.lead_id)
        db.add(saved)
    saved.details = json.dumps(details)
    access.published_price = access.published_cuft = access.published_at = None
    db.commit()
    return apply_spark_results_to_lead(access.lead_id, '', db, expected_report_id=report_id)
