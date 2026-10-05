"""Atomic inventory edits: mutate only requested inventory records."""
import json
import re
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from models import Lead, LeadJob, LeadLiveSwitch, LeadSparkInventoryItem, InventoryRoomType
from manual_inventory import InventoryRowChanges
from spark_history import remember_report


class ActionRow(InventoryRowChanges):
    catalog_item_id: str | None = None
    mover_pack: bool | None = None
    reference_name: str | None = Field(default=None, max_length=200)
    unit_weight: Decimal = Field(default=0, ge=0, le=100000, allow_inf_nan=False)


class InventoryAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['room_add', 'room_remove', 'room_rename', 'row_add', 'row_remove', 'row_update']
    room: str = Field(min_length=1, max_length=100)
    room_type_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    expected: ActionRow | None = None
    value: ActionRow | None = None


class InventoryActionsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    report_id: str | None = None
    actions: list[InventoryAction] = Field(min_length=1, max_length=1000)


def save_inventory_actions(body, access, db):
    job = db.query(LeadJob).filter_by(id=access.job_id, lead_id=access.lead_id).with_for_update().one()
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=access.lead_id).with_for_update().first()
    details = json.loads(saved.details or '{}') if saved else {}
    receipts = details.get('inventory_action_receipts', [])
    active = details.get('last_spark_status') == 'completed' and bool(details.get('last_spark_id'))
    if (details.get('last_spark_id') if active else None) != body.report_id:
        raise HTTPException(409, 'The report changed. Reopen the inventory before editing.')
    if str(body.request_id) in receipts:
        return {'ok': True}
    draft = details.get('inventory_draft') or {}
    source = details.get('spark_inventory_snapshot', []) if active else draft.get('rows', [])
    rows = [dict(row) for row in source]
    from catalog_names import resolve_catalog_names
    display_names = {id(row): resolved.get('name', row.get('name', ''))
                     for row, resolved in zip(rows, resolve_catalog_names(rows, db))}
    rooms = [{key: value for key, value in room.items() if key != 'items'}
             for room in (details.get('manual_rooms', []) if active else draft.get('rooms', []))]
    types = {row.id for row in db.query(InventoryRoomType).all()}
    default_type = next(iter(types), None)
    for row in rows:
        if not any(room['name'] == row.get('room', 'Other items') for room in rooms):
            rooms.append({'name': row.get('room', 'Other items'), 'room_type_id': default_type})
    records = db.query(LeadSparkInventoryItem).filter_by(job_id=job.id).all() if active else []
    by_order = {record.sort_order: record for record in records}
    by_id = {record.id: record for record in records}
    bindings = {}
    bound = set()
    for index, row in enumerate(rows):
        if row.get('going') is False:
            bindings[id(row)] = None
            continue
        record = by_id.get(row.get('_inventory_record_id')) or by_order.get(index)
        same = lambda value: (value.name == row.get('name') and value.amount == Decimal(str(row.get('amount') or 0))
                              and value.cuft == Decimal(str(row.get('cuft') or 0)))
        if record is None or record.id in bound or not same(record):
            matches = [value for value in records if value.id not in bound and same(value)]
            record = matches[0] if matches else None
        if record is None and records:
            raise HTTPException(409, 'The stored inventory changed. Refresh before editing.')
        bindings[id(row)] = record
        if record is not None:
            bound.add(record.id)
    next_order = max(by_order, default=-1) + 1
    removed = []

    def fail():
        raise HTTPException(409, 'This inventory changed. Reopen the list before editing.')

    def find_room(name):
        matches = [room for room in rooms if room['name'] == name]
        if len(matches) != 1:
            fail()
        return matches[0]

    def matches(row, expected):
        normalize = lambda name: re.sub(r'\s*\((CP|PBO)\)\s*$', '', name, flags=re.I).strip()
        quantity = int(row.get('amount') or 1)
        unit = Decimal(str(row.get('unit_cuft', float(row.get('cuft') or 0) / quantity)))
        return (normalize(display_names.get(id(row), row.get('name', ''))) == normalize(expected.name)
                and quantity == expected.quantity and abs(unit - expected.cuft) < Decimal('0.000001')
                and (row.get('going') is not False) == expected.going)

    for action in body.actions:
        if action.kind == 'room_add':
            if not action.room.strip() or action.room_type_id not in types or any(room['name'] == action.room for room in rooms):
                fail()
            rooms.append({'name': action.room, 'room_type_id': action.room_type_id})
            continue
        room = find_room(action.room)
        if action.kind == 'room_remove':
            victims = [row for row in rows if row.get('room') == action.room]
            removed.extend(victims)
            rows = [row for row in rows if row.get('room') != action.room]
            rooms.remove(room)
            continue
        if action.kind == 'room_rename':
            if not action.name or not action.name.strip() or any(other is not room and other['name'] == action.name for other in rooms):
                fail()
            for row in rows:
                if row.get('room') == action.room:
                    row['room'] = action.name
            room['name'] = action.name
            continue
        old = None
        if action.kind != 'row_add':
            if action.expected is None:
                fail()
            candidates = [row for row in rows if row.get('room') == action.room and matches(row, action.expected)]
            if len(candidates) != 1:
                fail()
            old = candidates[0]
        if action.kind == 'row_remove':
            rows.remove(old)
            removed.append(old)
            continue
        value = action.value
        if value is None or not value.name.strip():
            raise HTTPException(422, 'Enter valid inventory item details.')
        row = old if old is not None else {}
        unit_weight = Decimal(str(row.get('unit_weight', value.unit_weight)))
        row.update(name=value.name.strip(), room=action.room, amount=value.quantity, unit_cuft=float(value.cuft),
                   unit_weight=float(unit_weight), cuft=float(value.cuft * value.quantity) if value.going else 0,
                   weight=float(unit_weight * value.quantity) if value.going else 0, going=value.going,
                   name_override=value.name_override, mover_pack=value.mover_pack,
                   reference_name=row.get('reference_name') or value.reference_name or value.name)
        if old is None:
            row.update(item_id=value.catalog_item_id or 'custom-' + str(uuid4()), catalog_item_id=value.catalog_item_id, custom=True)
            rows.append(row)
    if len(rooms) > 100 or len(rows) > 60000:
        raise HTTPException(422, 'The inventory is too large.')
    volume = sum(float(row.get('cuft') or 0) for row in rows if row.get('going') is not False)
    weight = sum(float(row.get('weight') or 0) for row in rows if row.get('going') is not False)
    for room in rooms:
        room['items'] = [row for row in rows if row.get('room') == room['name']]
    if active:
        def packed_boxes(contents):
            counts = {}
            for row in contents:
                name = row.get('name', '')
                if not re.search(r'\bbox(?:es)?\b|\bdish\s*pack\b', name, re.I):
                    continue
                normalize = lambda text: re.sub(r'\s+', ' ', text.strip().lower())
                base = re.sub(r'\s*\((?:CP|PBO)\)\s*$', '', name, flags=re.I)
                key = f"{normalize(row.get('room') or 'Other items')}:{normalize(base)}"
                counts.setdefault(key, 0)
                if row.get('going') is not False and (row.get('mover_pack') is True or re.search(r'\(CP\)\s*$', name, re.I)):
                    counts[key] += int(row.get('amount') or 1)
            return counts
        previous_boxes, updated_boxes = packed_boxes(source), packed_boxes(rows)
        changed_boxes = {key for key in previous_boxes.keys() | updated_boxes.keys()
                         if previous_boxes.get(key, 0) != updated_boxes.get(key, 0)}
        if changed_boxes:
            selection = json.loads(job.customer_packing_package or '{}')
            if selection.get('mode') != 'full':
                quantities = selection.setdefault('box_quantities', {})
                for key in changed_boxes:
                    quantities[str(uuid5(NAMESPACE_URL, f'inventory-box:{job.id}:{key}'))] = updated_boxes.get(key, 0)
                job.customer_packing_package = json.dumps(selection)
        for row in removed:
            if bindings.get(id(row)) is not None:
                db.delete(bindings[id(row)])
        for index, row in enumerate(rows):
            record = bindings.get(id(row))
            if row.get('going') is False:
                if record is not None:
                    db.delete(record)
                continue
            if record is None:
                record = LeadSparkInventoryItem(id=str(uuid4()), job_id=job.id, sort_order=next_order)
                next_order += 1
                db.add(record)
            # SQLAlchemy emits UPDATE only for values that actually changed.
            record.name, record.amount, record.cuft = row['name'], row['amount'], Decimal(str(row.get('cuft') or 0))
            row['_inventory_record_id'] = record.id
        lead = db.get(Lead, access.lead_id)
        lead.volume, lead.weight = Decimal(str(volume)), Decimal(str(weight))
        access.published_cuft = lead.volume
        details.update(spark_inventory_snapshot=rows, question_original_rows=[dict(row) for row in rows],
                       manual_rooms=rooms, spark_extracted_cuft=volume, spark_extracted_weight=weight,
                       spark_extracted_id=body.report_id, spark_pricing_ready=False)
        details.pop('report_question_answers', None)
        details.pop('question_excluded_items', None)
    if not active or draft:
        # This existing JSON snapshot is shared storage, not a replacement of
        # inventory table records. Keep report-generation input synchronized.
        input_rooms = [{**{key: room[key] for key in ('name', 'room_type_id')}, 'items': [], 'custom_items': [
            {'id': str(uuid4()), 'name': row['name'], 'cuft': row.get('unit_cuft') or float(row.get('cuft') or 0) / max(1, row['amount']),
             'quantity': row['amount'], 'going': row.get('going') is not False, 'name_override': row.get('name_override', False),
             'catalog_item_id': row.get('catalog_item_id') or (row.get('item_id') if not str(row.get('item_id', '')).startswith('custom-') else None),
             'reference_name': row.get('reference_name'), 'mover_pack': row.get('mover_pack')}
            for row in room['items']]} for room in rooms]
        details['inventory_draft'] = {'body': {'request_id': str(body.request_id), 'rooms': input_rooms},
                                      'rows': rows, 'rooms': rooms, 'cuft': volume, 'weight': weight}
    if active:
        remember_report(details)
    details['inventory_action_receipts'] = (receipts + [str(body.request_id)])[-100:]
    if saved is None:
        saved = LeadLiveSwitch(lead_id=access.lead_id)
        db.add(saved)
    saved.details = json.dumps(details)
    db.commit()
    return {'ok': True}
