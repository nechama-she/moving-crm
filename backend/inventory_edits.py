"""Sparse inventory edits addressed by IDs, with joined catalog display names."""
import hashlib
import json
import re
from decimal import Decimal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from models import (Lead, LeadJob, LeadLiveSwitch, LeadSparkInventoryItem, InventoryRoomType,
                    InventoryCatalogItem, InventoryEditState, InventoryEditRoom, InventoryEditItem)
from spark_history import remember_report
from item_selectors import inventory_selectors


class Fields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=999, strict=True)
    cuft: Decimal | None = Field(default=None, gt=0, le=10000, allow_inf_nan=False)
    going: bool | None = None
    mover_pack: bool | None = None
    room_id: UUID | None = None
    selections: dict[str, str] = Field(default_factory=dict, max_length=30)


class Patch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    fields: Fields


class Addition(Fields):
    id: UUID
    room_id: UUID
    quantity: int = Field(ge=1, le=999, strict=True)
    catalog_item_id: str | None = Field(default=None, max_length=100)
    unit_weight: Decimal = Field(default=Decimal(0), ge=0, le=100000, allow_inf_nan=False)


class RoomAddition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    name: str = Field(min_length=1, max_length=100)
    room_type_id: str


class RoomPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    name: str = Field(min_length=1, max_length=100)


class RoomEdits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    update: list[RoomPatch] = Field(default_factory=list, max_length=100)
    delete: list[UUID] = Field(default_factory=list, max_length=100)
    add: list[RoomAddition] = Field(default_factory=list, max_length=100)


class InventoryEdits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    revision: UUID
    report_id: str | None = None
    update: list[Patch] = Field(default_factory=list, max_length=1000)
    delete: list[UUID] = Field(default_factory=list, max_length=1000)
    add: list[Addition] = Field(default_factory=list, max_length=1000)
    rooms: RoomEdits = Field(default_factory=RoomEdits)


def validated_selections(values, definitions, previous=None):
    options = {s['id']: s['options'] for s in definitions}
    for key, value in values.items():
        if previous and previous.get(key) == value:
            continue  # Preserve previously saved choices when catalog options change.
        if value not in options.get(key, []):
            raise HTTPException(422, 'This item option is unavailable. Reopen the inventory to refresh its selectors.')
    return json.dumps(values)


def source(details):
    active = details.get('last_spark_status') == 'completed' and bool(details.get('last_spark_id'))
    draft = details.get('inventory_draft') or {}
    return (details.get('last_spark_id') if active else None,
            details.get('spark_inventory_snapshot', []) if active else draft.get('rows', []),
            details.get('manual_rooms', []) if active else draft.get('rooms', []))


def source_hash(details):
    return hashlib.sha256(json.dumps(source(details), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def lock(access, db):
    job = db.query(LeadJob).filter_by(id=access.job_id, lead_id=access.lead_id).with_for_update().one()
    saved = db.query(LeadLiveSwitch).filter_by(lead_id=access.lead_id).with_for_update().first()
    details = json.loads(saved.details or '{}') if saved else {}
    state = db.get(InventoryEditState, job.id)
    return job, saved, details, state


def base_name(name):
    return re.sub(r'\s*\((?:CP|PBO)\)\s*$', '', name, flags=re.I).strip()


def joined_rows(job_id, db):
    # The database resolves catalog names; no full catalog load or name matching.
    return db.execute(select(InventoryEditItem, InventoryCatalogItem.name).outerjoin(
        InventoryCatalogItem, InventoryEditItem.catalog_item_id == InventoryCatalogItem.id
    ).where(InventoryEditItem.job_id == job_id).order_by(InventoryEditItem.sort_order, InventoryEditItem.id)).all()


def display_name(item, catalog_name):
    name = item.name if item.name is not None else catalog_name
    name = name or 'Item'
    if item.mover_pack is not None:
        name = base_name(name) + (' (CP)' if item.mover_pack else ' (PBO)')
    return name


def load_inventory_editor(access, db):
    job, saved, details, state = lock(access, db)
    report_id, rows, rooms = source(details)
    fingerprint = source_hash(details)
    if state is None or state.source_hash != fingerprint:
        # Import existing reports/drafts once, or after another report producer changes them.
        from catalog_names import resolve_catalog_names
        catalog = db.query(InventoryCatalogItem).all()
        resolved = resolve_catalog_names(rows, catalog=catalog)
        catalog_ids = {row.id for row in catalog}
        owned_items = {r.id for r in db.query(InventoryEditItem.id).filter_by(job_id=job.id)}
        owned_rooms = {r.id for r in db.query(InventoryEditRoom.id).filter_by(job_id=job.id)}
        db.query(InventoryEditItem).filter_by(job_id=job.id).delete(synchronize_session=False)
        db.query(InventoryEditRoom).filter_by(job_id=job.id).delete(synchronize_session=False)
        room_map, room_aliases = {}, {}
        type_ids = [row.id for row in db.query(InventoryRoomType.id).order_by(InventoryRoomType.sort_order)]
        default_type = type_ids[0] if type_ids else None
        for room in rooms:
            rid = room.get('id') or str(uuid4())
            original_id = rid
            if rid not in owned_rooms and db.get(InventoryEditRoom, rid) is not None: rid = str(uuid4())
            room_aliases[original_id] = rid
            room_map[rid] = InventoryEditRoom(id=rid, job_id=job.id, name=room['name'],
                room_type_id=room.get('room_type_id') if room.get('room_type_id') in type_ids else default_type,
                sort_order=len(room_map))
        records = db.query(LeadSparkInventoryItem).filter_by(job_id=job.id).all() if report_id else []
        used, row_ids, pending_items = set(), set(), []
        for index, (row, named) in enumerate(zip(rows, resolved)):
            room_name = row.get('room') or 'Other items'
            room = room_map.get(room_aliases.get(row.get('room_id'), row.get('room_id')))
            if room is None:
                room = next((r for r in room_map.values() if r.name == room_name), None)
            if room is None:
                room = InventoryEditRoom(id=str(uuid4()), job_id=job.id, name=room_name,
                    room_type_id=default_type, sort_order=len(room_map))
                room_map[room.id] = room
            record = next((r for r in records if r.id == row.get('_inventory_record_id') and r.id not in used), None)
            if record is None and row.get('going') is not False:
                record = next((r for r in records if r.id not in used and r.name == row['name']
                               and r.amount == Decimal(str(row.get('amount') or 0))
                               and abs(r.cuft - Decimal(str(row.get('cuft') or 0))) < Decimal('0.0051')), None)
            if record: used.add(record.id)
            cid = named.get('catalog_item_id') or named.get('item_id')
            cid = cid if cid in catalog_ids else None
            qty = max(1, int(row.get('amount') or 1))
            name = row['name']
            pack = row.get('mover_pack')
            if pack is None and re.search(r'\((?:CP|PBO)\)\s*$', name, re.I):
                pack = bool(re.search(r'\(CP\)\s*$', name, re.I))
            # Preserve custom names; store no duplicate name for catalog defaults.
            override = base_name(name) if cid is None or row.get('name_override') else None
            row_id = row.get('inventory_row_id') or (record.id if record else str(uuid4()))
            if row_id in row_ids or (row_id not in owned_items and db.get(InventoryEditItem, row_id) is not None): row_id = str(uuid4())
            row_ids.add(row_id)
            item = InventoryEditItem(id=row_id, job_id=job.id,
                room_id=room.id, catalog_item_id=cid, name=override,
                quantity=qty, unit_cuft=Decimal(str(row.get('unit_cuft') or float(row.get('cuft') or 0)/qty or 0.01)),
                unit_weight=Decimal(str(row.get('unit_weight') or float(row.get('weight') or 0)/qty)),
                going=row.get('going') is not False, mover_pack=pack, sort_order=index,
                selections=json.dumps(row.get('selections') or {}),
                inventory_record_id=record.id if record else None)
            pending_items.append(item)
        # Flush parents first, including databases that enforce foreign keys immediately.
        for room in room_map.values(): db.add(room)
        db.flush()
        db.add_all(pending_items)
        if state is None:
            state = InventoryEditState(job_id=job.id)
            db.add(state)
        state.source_hash, state.report_id, state.revision, state.receipts = fingerprint, report_id, str(uuid4()), '{}'
        db.commit()
    rooms = db.query(InventoryEditRoom).filter_by(job_id=job.id).order_by(InventoryEditRoom.sort_order).all()
    result = {room.id: dict(id=room.id, name=room.name, room_type_id=room.room_type_id or '', items={}, custom_items=[]) for room in rooms}
    inventory_rows = joined_rows(job.id, db)
    selectors = inventory_selectors(access, db)
    for item, name in inventory_rows:
        result[item.room_id]['custom_items'].append(dict(id=item.id, name=display_name(item, name),
            catalog_item_id=item.catalog_item_id, name_override=item.name is not None,
            quantity=item.quantity, cuft=float(item.unit_cuft), unit_weight=float(item.unit_weight),
            going=item.going, mover_pack=item.mover_pack, selections=json.loads(item.selections or '{}'),
            selectors=selectors.get(item.catalog_item_id, [])))
    return dict(revision=state.revision, report_id=report_id, rooms=list(result.values()))


def save_inventory_edits(body, access, db):
    job, saved, details, state = lock(access, db)
    selectors = inventory_selectors(access, db)
    if state is None:
        raise HTTPException(409, 'Open the inventory before editing.')
    receipts = json.loads(state.receipts or '{}')
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    receipt = receipts.get(str(body.request_id))
    if receipt:
        if receipt['digest'] != digest: raise HTTPException(409, 'Request ID already used for a different edit.')
        return dict(ok=True, revision=receipt['revision'])
    conflicts = []
    if str(body.revision) != state.revision:
        conflicts.append(f'editor revision mismatch (sent {body.revision}, current {state.revision})')
    if body.report_id != state.report_id:
        conflicts.append(f'report mismatch (sent {body.report_id}, current {state.report_id})')
    if source_hash(details) != state.source_hash:
        conflicts.append('report/draft inventory snapshot changed outside this editor revision')
    if conflicts:
        raise HTTPException(409, 'Inventory conflict: ' + '; '.join(conflicts) + '. Reopen it before editing.')
    for group in (body, body.rooms):
        ids = [str(x.id) for x in group.update] + [str(x) for x in group.delete] + [str(x.id) for x in group.add]
        if len(ids) != len(set(ids)): raise HTTPException(422, 'Each ID must appear only once per batch.')
    room_ids = {r.id for r in db.query(InventoryEditRoom.id).filter_by(job_id=job.id)}
    deleted_rooms = {str(x) for x in body.rooms.delete}
    if not deleted_rooms <= room_ids: raise HTTPException(409, 'Room does not belong to this inventory.')
    for item in body.rooms.add:
        if not item.name.strip() or db.get(InventoryEditRoom, str(item.id)):
            raise HTTPException(422, 'Invalid or duplicate room.')
        if not db.get(InventoryRoomType, item.room_type_id): raise HTTPException(422, 'Unknown room type.')
        db.add(InventoryEditRoom(id=str(item.id), job_id=job.id, name=item.name.strip(), room_type_id=item.room_type_id, sort_order=len(room_ids)))
        room_ids.add(str(item.id))
    for item in body.rooms.update:
        if str(item.id) not in room_ids or not item.name.strip(): raise HTTPException(409, 'Invalid room update.')
        db.query(InventoryEditRoom).filter_by(id=str(item.id), job_id=job.id).update({'name':item.name.strip()}, synchronize_session=False)
    db.flush()
    room_ids -= deleted_rooms
    requested = {str(e.id) for e in body.update} | {str(e) for e in body.delete}
    query = db.query(InventoryEditItem).filter(InventoryEditItem.job_id == job.id)
    from sqlalchemy import or_
    targets = query.filter(or_(InventoryEditItem.id.in_(requested), InventoryEditItem.room_id.in_(deleted_rooms))).all() if requested or deleted_rooms else []
    target_map = {row.id:row for row in targets}
    if not requested <= target_map.keys(): raise HTTPException(409, 'Inventory row does not belong to this move or was deleted.')
    deleted = {str(x) for x in body.delete} | {r.id for r in targets if r.room_id in deleted_rooms}
    changed = []
    for edit in body.update:
        row = target_map[str(edit.id)]
        if row.id in deleted: raise HTTPException(422, 'Cannot update a deleted row.')
        fields = edit.fields.model_dump(exclude_unset=True)
        if not fields: raise HTTPException(422, 'No fields supplied.')
        for key, value in fields.items():
            if key not in ('name', 'mover_pack') and value is None: raise HTTPException(422, f'{key} cannot be null.')
            if key == 'room_id':
                value = str(value)
                if value not in room_ids: raise HTTPException(409, 'Target room does not belong to this inventory.')
            if key == 'name':
                if value is None and not row.catalog_item_id: raise HTTPException(422, 'Custom items need a name.')
                if value is not None and not value.strip(): raise HTTPException(422, 'Name cannot be blank.')
                value = value.strip() if value is not None else None
            if key == 'selections':
                value = validated_selections(value, selectors.get(row.catalog_item_id, []), json.loads(row.selections or '{}'))
            setattr(row, 'unit_cuft' if key == 'cuft' else key, value)
        changed.append(row)
    next_order = (db.query(func.max(InventoryEditItem.sort_order)).filter_by(job_id=job.id).scalar() or 0) + 1 if body.add else 0
    for item in body.add:
        key = str(item.id)
        if db.get(InventoryEditItem, key): raise HTTPException(409, 'Inventory row ID already exists.')
        if str(item.room_id) not in room_ids: raise HTTPException(409, 'Target room does not belong to this inventory.')
        catalog = db.get(InventoryCatalogItem, item.catalog_item_id) if item.catalog_item_id else None
        if item.catalog_item_id and (not catalog or catalog.deleted): raise HTTPException(422, 'Unknown catalog item.')
        if catalog is None and (not item.name or not item.name.strip()): raise HTTPException(422, 'Custom items need a name.')
        cuft = item.cuft if item.cuft is not None else catalog.cuft if catalog else None
        if cuft is None or cuft <= 0: raise HTTPException(422, 'Item volume must be positive.')
        row = InventoryEditItem(id=key, job_id=job.id, room_id=str(item.room_id), catalog_item_id=item.catalog_item_id,
            name=item.name.strip() if item.name else None, quantity=item.quantity, unit_cuft=cuft,
            unit_weight=catalog.weight if catalog else item.unit_weight, going=item.going is not False,
            mover_pack=item.mover_pack, sort_order=next_order,
            selections=validated_selections(item.selections, selectors.get(item.catalog_item_id, [])))
        next_order += 1
        db.add(row)
        changed.append(row)
    # UPDATE/DELETE only affected SQL inventory rows, always scoped to this move.
    record_ids = {r.inventory_record_id for r in targets if r.inventory_record_id}
    records = {r.id:r for r in db.query(LeadSparkInventoryItem).filter(
        LeadSparkInventoryItem.job_id == job.id, LeadSparkInventoryItem.id.in_(record_ids)).all()} if record_ids else {}
    for key in deleted:
        row = target_map[key]
        if row.inventory_record_id in records: db.delete(records[row.inventory_record_id])
        db.delete(row)
    db.flush()
    for key in deleted_rooms:
        db.query(InventoryEditRoom).filter_by(id=key, job_id=job.id).delete(synchronize_session=False)
    db.flush()
    joined = joined_rows(job.id, db)
    if len(joined) > 60000 or len(room_ids) > 100: raise HTTPException(422, 'Inventory is too large.')
    names = {r.id:display_name(r,n) for r,n in joined}
    if state.report_id:
        for row in changed:
            record = records.get(row.inventory_record_id)
            if not row.going:
                if record: db.delete(record)
                row.inventory_record_id = None
                continue
            if record is None:
                record = LeadSparkInventoryItem(id=row.id, job_id=job.id, sort_order=row.sort_order)
                db.add(record)
            record.name, record.amount, record.cuft = names[row.id], row.quantity, row.unit_cuft * row.quantity
            row.inventory_record_id = record.id
    # Named compatibility snapshots are derived from JOINs, not used as row identity.
    project(job, access, details, joined, db)
    if saved is None:
        saved = LeadLiveSwitch(lead_id=access.lead_id)
        db.add(saved)
    saved.details = json.dumps(details)
    state.source_hash, state.revision = source_hash(details), str(uuid4())
    receipts[str(body.request_id)] = dict(digest=digest, revision=state.revision)
    state.receipts = json.dumps(dict(list(receipts.items())[-100:]))
    db.commit()
    return dict(ok=True, revision=state.revision)


def project(job, access, details, joined, db):
    report_id, old_rows, _ = source(details)
    rooms = db.query(InventoryEditRoom).filter_by(job_id=job.id).order_by(InventoryEditRoom.sort_order).all()
    room_names = {r.id:r.name for r in rooms}
    rows = [dict(inventory_row_id=r.id, room_id=r.room_id, name=display_name(r,name), room=room_names[r.room_id],
        amount=r.quantity, unit_cuft=float(r.unit_cuft), unit_weight=float(r.unit_weight),
        cuft=float(r.unit_cuft*r.quantity) if r.going else 0, weight=float(r.unit_weight*r.quantity) if r.going else 0,
        going=r.going, mover_pack=r.mover_pack, catalog_item_id=r.catalog_item_id, item_id=r.catalog_item_id or 'custom-'+r.id,
        name_override=r.name is not None, _inventory_record_id=r.inventory_record_id,
        selections=json.loads(r.selections or '{}')) for r,name in joined]
    serialized_rooms = [dict(id=r.id, name=r.name, room_type_id=r.room_type_id or '', items=[x for x in rows if x['room_id']==r.id]) for r in rooms]
    volume, weight = sum(r['cuft'] for r in rows), sum(r['weight'] for r in rows)
    if report_id:
        def counts(contents):
            result = {}
            for row in contents:
                if not re.search(r'\bbox(?:es)?\b|\bdish\s*pack\b',row['name'],re.I): continue
                norm = lambda value: re.sub(r'\s+',' ',value.strip().lower())
                key = f"{norm(row.get('room') or 'Other items')}:{norm(base_name(row['name']))}"
                result.setdefault(key,0)
                if row.get('going') is not False and (row.get('mover_pack') is True or re.search(r'\(CP\)\s*$',row['name'],re.I)):
                    result[key] += int(row['amount'])
            return result
        before, after = counts(old_rows), counts(rows)
        selection = json.loads(job.customer_packing_package or '{}')
        if selection.get('mode') != 'full':
            for key in before.keys() | after.keys():
                if before.get(key,0) != after.get(key,0):
                    selection.setdefault('box_quantities',{})[str(uuid5(NAMESPACE_URL,f'inventory-box:{job.id}:{key}'))] = after.get(key,0)
            job.customer_packing_package = json.dumps(selection)
        lead = db.get(Lead,access.lead_id)
        lead.volume, lead.weight, access.published_cuft = Decimal(str(volume)), Decimal(str(weight)), Decimal(str(volume))
        details.update(spark_inventory_snapshot=rows, question_original_rows=[dict(r) for r in rows], manual_rooms=serialized_rooms,
                       spark_extracted_cuft=volume,spark_extracted_weight=weight,spark_extracted_id=report_id,spark_pricing_ready=False)
        details.pop('report_question_answers',None)
        details.pop('question_excluded_items',None)
    if not report_id or details.get('inventory_draft'):
        input_rooms = [dict(name=r['name'],room_type_id=r['room_type_id'],items=[],custom_items=[dict(
            id=x['inventory_row_id'],name=x['name'],quantity=x['amount'],cuft=x['unit_cuft'],going=x['going'],
            mover_pack=x['mover_pack'],selections=x['selections'],catalog_item_id=x['catalog_item_id'],name_override=x['name_override']) for x in r['items']]) for r in serialized_rooms]
        details['inventory_draft']=dict(body=dict(request_id=str(uuid4()),rooms=input_rooms),rows=rows,rooms=serialized_rooms,cuft=volume,weight=weight)
    if report_id: remember_report(details)
