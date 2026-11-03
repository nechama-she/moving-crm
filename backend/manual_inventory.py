"""Customer-entered room inventories use catalog values and the shared pricing flow."""
import json
import re
import time
from decimal import Decimal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from models import InventoryRoomType, InventoryCatalogItem, LeadLiveSwitch, LeadJob, Lead
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


class InventoryRowValues(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)
    cuft: Decimal = Field(gt=0, le=10000, allow_inf_nan=False)
    quantity: int = Field(ge=1, le=999, strict=True)
    going: bool = True


class InventoryRowChanges(InventoryRowValues):
    name_override: bool = False


class InventoryRowPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report_id: str | None = Field(default=None, max_length=100)
    room: str = Field(min_length=1, max_length=100)
    expected: InventoryRowValues
    changes: InventoryRowChanges


def update_inventory_row(body, access, db):
    """Optimistically update one inventory item, without replacing sibling rows."""
    from models import LeadSparkInventoryItem
    from catalog_names import resolve_catalog_names
    job = db.query(LeadJob).filter_by(id=access.job_id, lead_id=access.lead_id).with_for_update().one()
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=access.lead_id).with_for_update().first()
    details = json.loads(saved.details or '{}') if saved else {}
    active = body.report_id is not None
    if active and (details.get('last_spark_id') != body.report_id or details.get('last_spark_status') != 'completed'):
        raise HTTPException(409, 'The report changed. Reopen the inventory before editing.')
    draft = details.get('inventory_draft')
    if not active and details.get('last_spark_status') == 'completed' and details.get('spark_inventory_snapshot'):
        raise HTTPException(409, 'The report changed. Reopen the inventory before editing.')
    rows = details.get('spark_inventory_snapshot', []) if active else (draft or {}).get('rows', [])

    def base_name(name):
        return re.sub(r'\s*\((?:CP|PBO)\)\s*$', '', name, flags=re.I).strip()

    def matches(row):
        count = int(row.get('amount') or row.get('quantity') or 1)
        unit = Decimal(str(row.get('unit_cuft') if row.get('unit_cuft') is not None else float(row.get('cuft') or 0) / count))
        return (row.get('room') == body.room and base_name(row.get('name', '')) == base_name(body.expected.name)
                and count == body.expected.quantity and abs(unit - body.expected.cuft) < Decimal('0.000001')
                and (row.get('going') is not False) == body.expected.going)

    resolved = resolve_catalog_names(rows, db)
    indexes = [index for index, row in enumerate(resolved) if matches(row)]
    if len(indexes) != 1:
        raise HTTPException(409, 'This item changed or is ambiguous. Reopen the inventory before editing.')
    index = indexes[0]
    old = rows[index]
    changes = body.changes
    if not changes.name.strip():
        raise HTTPException(422, 'Enter an item name.')
    unit_weight = Decimal(str(old.get('unit_weight') or 0))
    updated = {**resolved[index], 'name': changes.name.strip(), 'name_override': changes.name_override,
               'unit_cuft': float(changes.cuft), 'amount': changes.quantity, 'going': changes.going,
               'cuft': float(changes.cuft * changes.quantity) if changes.going else 0,
               'weight': float(unit_weight * changes.quantity) if changes.going else 0,
               'reference_name': old.get('reference_name') or old.get('name')}
    rows[index] = updated

    def replace_in_rooms(rooms):
        # Locate by the old values; repeated room labels are not assumed unique.
        for room in rooms:
            for position, row in enumerate(room.get('items', [])):
                if row == old:
                    room['items'][position] = dict(updated)
                    return

    if active:
        target = db.query(LeadSparkInventoryItem).filter_by(job_id=job.id, sort_order=index).one_or_none()
        if old.get('going') is not False and (target is None or target.name != old.get('name')
                or Decimal(str(target.amount)) != Decimal(str(old.get('amount') or 0))):
            raise HTTPException(409, 'The stored inventory changed. Reopen it before editing.')
        if changes.going:
            if target is None:
                target = LeadSparkInventoryItem(job_id=job.id, sort_order=index)
                db.add(target)
            target.name, target.amount, target.cuft = updated['name'], changes.quantity, Decimal(str(updated['cuft']))
        elif target is not None:
            db.delete(target)
        replace_in_rooms(details.get('manual_rooms', []))
        details['question_original_rows'] = [dict(row) for row in rows]
        details.pop('report_question_answers', None)
        details.pop('question_excluded_items', None)
        volume = sum(Decimal(str(row.get('cuft') or 0)) for row in rows if row.get('going') is not False)
        weight = sum(Decimal(str(row.get('weight') or 0)) for row in rows if row.get('going') is not False)
        lead = db.get(Lead, access.lead_id)
        lead.volume, lead.weight = volume, weight
        access.published_cuft = volume
        details.update(spark_extracted_cuft=float(volume), spark_extracted_weight=float(weight), spark_pricing_ready=False)

    if draft:
        # Preserve the manual report input alongside the snapshot, without
        # rebuilding it from the catalog or dropping other saved custom rows.
        draft_indexes = [i for i, row in enumerate(draft['rows']) if row == old]
        if len(draft_indexes) != 1:
            # In draft-only mode rows above and draft.rows are the same list.
            draft_indexes = [index] if not active else []
        if draft_indexes:
            draft_index = draft_indexes[0]
            move_to = None
            offset = 0
            for room in draft['body']['rooms']:
                entries = room.get('items', []) + room.get('custom_items', [])
                if offset <= draft_index < offset + len(entries):
                    position = draft_index - offset
                    if position < len(room.get('items', [])):
                        original = room['items'].pop(position)
                        custom = {'id': str(uuid4()), 'catalog_item_id': original['item_id']}
                        room.setdefault('custom_items', []).append(custom)
                        move_to = offset + len(entries) - 1
                    else:
                        custom = room['custom_items'][position - len(room.get('items', []))]
                    custom.update(changes.model_dump(mode='json'), reference_name=updated['reference_name'])
                    break
                offset += len(entries)
            draft['rows'][draft_index] = dict(updated)
            replace_in_rooms(draft.get('rooms', []))
            if move_to is not None:
                draft['rows'].insert(move_to, draft['rows'].pop(draft_index))
                for room in draft.get('rooms', []):
                    positions = [i for i, row in enumerate(room.get('items', [])) if row == updated]
                    if positions:
                        room['items'].append(room['items'].pop(positions[0]))
                        break
            draft['cuft'] = sum(float(row.get('cuft') or 0) for row in draft['rows'] if row.get('going') is not False)
            draft['weight'] = sum(float(row.get('weight') or 0) for row in draft['rows'] if row.get('going') is not False)
    if active:
        remember_report(details)
    saved.details = json.dumps(details)
    db.commit()
    return {'ok': True}


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


def submit_inventory(body, access, db):
    from routes.liveswitch import apply_spark_results_to_lead
    rooms, rows, cuft, weight = build_inventory(body, db)
    save_service_defaults(rows, access, db)
    return submit_inventory_snapshot(body.model_dump(mode='json'), rooms, rows, cuft, weight, access, db)


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


def save_service_defaults(rows, access, db):
    from item_selectors import inventory_selectors, default_selections
    selectors = inventory_selectors(access, db, {row.get('catalog_item_id') or row.get('item_id') for row in rows})
    for row in rows:
        row['selections'] = default_selections(row.get('selections'), selectors.get(row.get('catalog_item_id') or row.get('item_id'), []))


def save_inventory_draft(body, access, db):
    rooms, rows, cuft, weight = build_inventory(body, db, allow_empty=True)
    save_service_defaults(rows, access, db)
    db.query(LeadJob).filter_by(id=access.job_id).with_for_update().one()
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=access.lead_id).with_for_update().first()
    details = json.loads(saved.details or '{}') if saved else {}
    details['inventory_draft'] = {'body': body.model_dump(mode='json'), 'rooms': rooms,
                                  'rows': rows, 'cuft': cuft, 'weight': weight}
    if not saved:
        saved = LeadLiveSwitch(lead_id=access.lead_id)
        db.add(saved)
    saved.details = json.dumps(details)
    db.commit()
    return {'ok': True}


def replace_current_inventory(body, access, db):
    """Replace the active report's editable inventory without replacing its media report."""
    from models import LeadSparkInventoryItem
    rooms, rows, cuft, weight = build_inventory(body, db, allow_empty=True)
    save_service_defaults(rows, access, db)
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=access.lead_id).with_for_update().first()
    details = json.loads(saved.details or '{}') if saved else {}
    report_id = details.get('last_spark_id')
    if not report_id or details.get('last_spark_status') != 'completed':
        raise HTTPException(409, 'The current inventory is not ready to edit.')
    details['spark_inventory_snapshot'] = rows
    details['question_original_rows'] = [dict(row) for row in rows]
    details['manual_rooms'] = rooms
    details['spark_extracted_cuft'] = cuft
    details['spark_extracted_weight'] = weight
    details['spark_pricing_ready'] = False
    details.pop('spark_extracted_id', None)
    from report_files import active_report_files
    if not active_report_files(access, db):
        # With no media, an explicit inventory save becomes the manual report input.
        details['inventory_draft'] = {'body': body.model_dump(mode='json'), 'rooms': rooms,
                                      'rows': rows, 'cuft': cuft, 'weight': weight}
    else:
        details.pop('inventory_draft', None)
    for key in ('question_excluded_items', 'report_question_answers'):
        details.pop(key, None)
    remember_report(details)
    saved.details = json.dumps(details)
    db.flush()
    # Inventory edits must retain the customer's packing choices, not stale name suffixes.
    job = db.get(LeadJob, access.job_id)
    lead = db.get(Lead, access.lead_id)
    # Save the compact inventory rows directly. Report processing includes
    # progress publications and extraction work that autosaves do not need.
    details = json.loads(saved.details or '{}')
    rows = details['spark_inventory_snapshot']
    lead.volume = Decimal(str(cuft))
    lead.weight = Decimal(str(weight))
    access.published_cuft = lead.volume
    details['spark_extracted_id'] = report_id
    details['spark_pricing_ready'] = False
    remember_report(details)
    saved.details = json.dumps(details)
    db.query(LeadSparkInventoryItem).filter_by(job_id=job.id).delete(synchronize_session=False)
    for index, row in enumerate(rows):
        if row.get('going') is False:
            continue
        db.add(LeadSparkInventoryItem(job_id=job.id, name=str(row.get('name') or 'Item'),
            cuft=Decimal(str(row.get('cuft') or 0)), amount=Decimal(str(row.get('amount') or 0)), sort_order=index))
    db.commit()
    return {'ok': True, 'cuft': cuft, 'weight': weight, 'inventory_count': len(rows), 'job_id': job.id}
