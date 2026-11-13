"""Sparse inventory edits addressed by IDs, with joined catalog display names."""
import hashlib
import json
import re
from decimal import Decimal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from models import (Lead, LeadJob, LeadLiveSwitch, InventoryRoomType,
                    InventoryCatalogItem, InventoryEditState, InventoryEditRoom, InventoryEditItem)
from item_selectors import inventory_selectors, ServiceSelections, default_selections


class Fields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=999, strict=True)
    cuft: Decimal | None = Field(default=None, gt=0, le=10000, allow_inf_nan=False)
    going: bool | None = None
    mover_pack: bool | None = None
    mover_pack_count: int | None = Field(default=None, ge=0, le=999, strict=True)
    room_id: UUID | None = None
    selections: ServiceSelections = Field(default_factory=dict)


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
    set_id: UUID | None = None
    set_name: str | None = Field(default=None, min_length=1, max_length=200)


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
        selected_options = [value] if isinstance(value, str) else list(value)
        if any(option not in options.get(key, []) for option in selected_options):
            raise HTTPException(422, 'This item option is unavailable. Reopen the inventory to refresh its selectors.')
    return json.dumps(default_selections({**(previous or {}), **values}, definitions))


def active_report(details):
    """The completed report the move's inventory belongs to, or None (no report, or new media archived it)."""
    return details.get('last_spark_id') if details.get('last_spark_status') == 'completed' and details.get('last_spark_id') else None


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


def pack_count(item):
    """Units of this row the movers pack, reading the older whole-row CP/PBO marking when that is all there is."""
    if item.mover_pack_count is not None:
        return min(item.mover_pack_count, item.quantity)
    if item.mover_pack is not None:
        return item.quantity if item.mover_pack else 0
    return None


def display_name(item, catalog_name):
    name = item.name if item.name is not None else catalog_name
    name = name or 'Item'
    if item.mover_pack is not None:
        name = base_name(name)
    return name


def load_inventory_editor(access, db):
    job, saved, details, state = lock(access, db)
    report_id = active_report(details)
    if state is None or state.report_id != report_id:
        # The tables keep the list; a new or archived report gives the window a new revision.
        state = _editor_state(job, state, db, report_id)
        db.commit()
    rooms = db.query(InventoryEditRoom).filter_by(job_id=job.id).order_by(InventoryEditRoom.sort_order).all()
    result = {room.id: dict(id=room.id, name=room.name, room_type_id=room.room_type_id or '', items={}, custom_items=[]) for room in rooms}
    inventory_rows = joined_rows(job.id, db)
    selectors = inventory_selectors(access, db, {item.catalog_item_id for item, _ in inventory_rows if item.catalog_item_id})
    defaults_saved = False
    for item, _ in inventory_rows:
        previous = json.loads(item.selections or '{}')
        selections = default_selections(previous, selectors.get(item.catalog_item_id, []))
        if selections != previous:
            item.selections = json.dumps(selections)
            defaults_saved = True
    if defaults_saved:
        if report_id:
            # Saved like an edit: the list is answered again and the estimate needs updating.
            list_edited(job, details, db)
            inventory_rows = joined_rows(job.id, db)
            if saved is None:
                saved = LeadLiveSwitch(lead_id=access.lead_id)
                db.add(saved)
            saved.details = json.dumps(details)
        state.revision = str(uuid4())
        db.commit()
    for item, name in inventory_rows:
        # The window shows the list as it ships: units an item answer took off are not in it.
        units = item.quantity - (item.excluded_quantity or 0)
        if units <= 0:
            continue
        packed = pack_count(item)
        result[item.room_id]['custom_items'].append(dict(id=item.id, name=display_name(item, name),
            catalog_item_id=item.catalog_item_id, name_override=item.name is not None,
            set_id=item.set_id, set_name=item.set_name,
            quantity=units, cuft=float(item.unit_cuft), unit_weight=float(item.unit_weight),
            going=item.going, mover_pack=item.mover_pack, mover_pack_count=None if packed is None else min(packed, units),
            selections=json.loads(item.selections or '{}'),
            selectors=selectors.get(item.catalog_item_id, [])))
    # The room types a room can be added as, in the same response: the window needs nothing else to open.
    room_types = [dict(id=row.id, name=row.name) for row in db.query(InventoryRoomType).order_by(InventoryRoomType.sort_order)]
    return dict(revision=state.revision, report_id=state.report_id, rooms=list(result.values()), room_types=room_types)


def save_inventory_edits(body, access, db):
    job, saved, details, state = lock(access, db)
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
    if conflicts:
        raise HTTPException(409, 'Inventory conflict: ' + '; '.join(conflicts) + '. Reopen it before editing.')
    if active_report(details):
        # The window edits the list as it ships: units item answers took off leave the list for good, as an edit
        # answers the list again.
        materialize_exclusions(job.id, db)
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
    selectors = inventory_selectors(access, db,
        {row.catalog_item_id for row in targets if row.catalog_item_id}
        | {item.catalog_item_id for item in body.add if item.catalog_item_id})
    if not requested <= target_map.keys(): raise HTTPException(409, 'Inventory row does not belong to this move or was deleted.')
    deleted = {str(x) for x in body.delete} | {r.id for r in targets if r.room_id in deleted_rooms}
    changed = []
    for edit in body.update:
        row = target_map[str(edit.id)]
        if row.id in deleted: raise HTTPException(422, 'Cannot update a deleted row.')
        fields = edit.fields.model_dump(exclude_unset=True)
        if not fields: raise HTTPException(422, 'No fields supplied.')
        for key, value in fields.items():
            if key not in ('name', 'mover_pack', 'mover_pack_count') and value is None: raise HTTPException(422, f'{key} cannot be null.')
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
        row.manual = True  # Edited by hand: a new report keeps it.
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
            mover_pack=item.mover_pack, mover_pack_count=item.mover_pack_count, sort_order=next_order,
            set_id=str(item.set_id) if item.set_id else None, set_name=item.set_name,
            selections=validated_selections(item.selections, selectors.get(item.catalog_item_id, [])), manual=True)
        next_order += 1
        db.add(row)
        changed.append(row)
    # UPDATE/DELETE only affected SQL inventory rows, always scoped to this move.
    for key in deleted:
        db.delete(target_map[key])
    db.flush()
    for key in deleted_rooms:
        db.query(InventoryEditRoom).filter_by(id=key, job_id=job.id).delete(synchronize_session=False)
    db.flush()
    if db.query(func.count(InventoryEditItem.id)).filter_by(job_id=job.id).scalar() > 60000 or len(room_ids) > 100:
        raise HTTPException(422, 'Inventory is too large.')
    if active_report(details):
        list_edited(job, details, db)
    if saved is None:
        saved = LeadLiveSwitch(lead_id=access.lead_id)
        db.add(saved)
    saved.details = json.dumps(details)
    state.revision = str(uuid4())
    receipts[str(body.request_id)] = dict(digest=digest, revision=state.revision)
    state.receipts = json.dumps(dict(list(receipts.items())[-100:]))
    db.commit()
    return dict(ok=True, revision=state.revision)


def list_rows(job_id, db, joined=None):
    """The inventory as rows and rooms, read from the inventory tables with catalog names joined."""
    joined = joined_rows(job_id, db) if joined is None else joined
    rooms = db.query(InventoryEditRoom).filter_by(job_id=job_id).order_by(InventoryEditRoom.sort_order).all()
    room_names = {r.id:r.name for r in rooms}
    rows = [dict(inventory_row_id=r.id, room_id=r.room_id, name=(r.name if r.name is not None else name) or 'Item', room=room_names[r.room_id],
        amount=r.quantity, unit_cuft=float(r.unit_cuft), unit_weight=float(r.unit_weight),
        cuft=float(r.unit_cuft*r.quantity) if r.going else 0, weight=float(r.unit_weight*r.quantity) if r.going else 0,
        going=r.going, mover_pack=None if pack_count(r) is not None else r.mover_pack, mover_pack_count=pack_count(r),
        catalog_item_id=r.catalog_item_id, item_id=r.catalog_item_id or 'custom-'+r.id,
        name_override=r.name is not None, excluded_quantity=r.excluded_quantity or 0,
        reference_name=r.reference_name, question_key=r.question_key or r.id,
        set_id=r.set_id, set_name=r.set_name, manual=r.manual,
        selections=json.loads(r.selections or '{}')) for r,name in joined]
    serialized_rooms = [dict(id=r.id, name=r.name, room_type_id=r.room_type_id or '', items=[x for x in rows if x['room_id']==r.id]) for r in rooms]
    return rows, serialized_rooms


def _editor_state(job, state, db, report_id):
    """The job's editor state with a new revision, so an open inventory window loads the list again."""
    state = state or db.get(InventoryEditState, job.id)
    if state is None:
        state = InventoryEditState(job_id=job.id, source_hash='')
        db.add(state)
    state.report_id, state.revision, state.receipts = report_id, str(uuid4()), '{}'
    return state


def _money(value):
    return Decimal(str(value or 0))


def shipping_rows(job_id, db, rows=None):
    """What ships: each going row less the units an item answer took off, with the volume and weight of those units."""
    rows = list_rows(job_id, db)[0] if rows is None else rows
    result = []
    for row in rows:
        units = row['amount'] - row.get('excluded_quantity', 0)
        if row.get('going') is False or units <= 0:
            continue
        packed = row.get('mover_pack_count')
        result.append(dict(row, amount=units, quantity=units,
                           cuft=float(_money(row['unit_cuft']) * units), weight=float(_money(row['unit_weight']) * units),
                           mover_pack_count=None if packed is None else min(packed, units)))
    return result


def _set_volume(job, details, volume, weight, db):
    from models import PublicMoveAccess
    lead = db.get(Lead, job.lead_id)
    lead.volume, lead.weight = volume, weight
    for link in db.query(PublicMoveAccess).filter_by(job_id=job.id).all():
        link.published_cuft = volume
    details['spark_extracted_cuft'], details['spark_extracted_weight'] = float(volume), float(weight)


def apply_inventory(job, details, db):
    """After a report or an item answer: the move's volume is what ships, plus the part of the report's total its items
    do not account for, rounded up to a whole cubic foot; its weight likewise, not rounded. Does not commit."""
    from decimal import ROUND_CEILING
    rows = shipping_rows(job.id, db)
    volume = sum((_money(r['unit_cuft']) * r['amount'] for r in rows), Decimal(0)) + _money(details.get('report_volume_offset'))
    weight = sum((_money(r['unit_weight']) * r['amount'] for r in rows), Decimal(0)) + _money(details.get('report_weight_offset'))
    volume = max(Decimal(0), volume).to_integral_value(rounding=ROUND_CEILING)
    weight = max(Decimal(0), weight)
    _set_volume(job, details, volume, weight, db)
    return volume, weight


def materialize_exclusions(job_id, db):
    """Units item answers took off leave the list for good. Does not commit."""
    for item in db.query(InventoryEditItem).filter(InventoryEditItem.job_id == job_id, InventoryEditItem.excluded_quantity > 0).all():
        if item.excluded_quantity >= item.quantity:
            db.delete(item)
            continue
        item.quantity -= item.excluded_quantity
        item.excluded_quantity = 0
        # A changed row is a new item to its questions: the answers that took units off do not apply again.
        item.question_key = str(uuid4())
        if item.mover_pack_count is not None:
            item.mover_pack_count = min(item.mover_pack_count, item.quantity)
    db.flush()


def list_edited(job, details, db):
    """The list was edited while a report is current: its answers start over, its volume is exactly what the rows add up
    to, and the estimate needs updating. Does not commit."""
    materialize_exclusions(job.id, db)
    for item, catalog_name in joined_rows(job.id, db):
        if item.name is not None and item.mover_pack is not None and base_name(item.name) != item.name:
            item.name = None if item.catalog_item_id and base_name(item.name) == catalog_name else base_name(item.name)
    db.flush()
    rows = list_rows(job.id, db)[0]
    volume = sum((_money(r['unit_cuft']) * r['amount'] for r in rows if r['going']), Decimal(0))
    weight = sum((_money(r['unit_weight']) * r['amount'] for r in rows if r['going']), Decimal(0))
    _set_volume(job, details, volume, weight, db)
    for key in ('report_question_answers', 'report_volume_offset', 'report_weight_offset'):
        details.pop(key, None)
    details.update(spark_extracted_id=active_report(details), spark_pricing_ready=False, report_edited=True)


def _write_rows(job, rows, rooms, db, keep_rooms=()):
    """Add the rows, and the rooms they are in, to the job's inventory tables. Rows carry their catalog ids from when
    the report ran; nothing is matched by name. keep_rooms: the job's rooms already in the tables."""
    from catalog_names import catalog_items
    catalog = catalog_items(rows, db)
    type_ids = [row.id for row in db.query(InventoryRoomType.id).order_by(InventoryRoomType.sort_order)]
    default_type = type_ids[0] if type_ids else None
    room_map = {room.id: room for room in keep_rooms}
    by_name = {room.name: room for room in keep_rooms}
    wanted = [room['id'] for room in rooms if room.get('id') and room['id'] not in room_map]
    taken = {r.id for r in db.query(InventoryEditRoom.id).filter(InventoryEditRoom.id.in_(wanted))} if wanted else set()
    aliases = {}
    for room in rooms:
        existing = room_map.get(room.get('id')) or by_name.get(room.get('name'))
        if existing is None:
            rid = room['id'] if room.get('id') and room['id'] not in taken else str(uuid4())
            existing = InventoryEditRoom(id=rid, job_id=job.id, name=room['name'], sort_order=len(room_map),
                room_type_id=room.get('room_type_id') if room.get('room_type_id') in type_ids else default_type)
            room_map[rid] = by_name[existing.name] = existing
            db.add(existing)
        if room.get('id'):
            aliases[room['id']] = existing.id
    start = (db.query(func.max(InventoryEditItem.sort_order)).filter_by(job_id=job.id).scalar() or 0) + 1 if keep_rooms else 0
    pending = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        room_id = row.get('room_id')
        room = (room_map.get(aliases.get(room_id, room_id)) if room_id else None) or by_name.get(row.get('room') or 'Other items')
        if room is None:
            room = InventoryEditRoom(id=str(uuid4()), job_id=job.id, name=row.get('room') or 'Other items',
                                     room_type_id=default_type, sort_order=len(room_map))
            room_map[room.id] = by_name[room.name] = room
            db.add(room)
        cid = row.get('catalog_item_id') or row.get('item_id')
        cid = cid if cid in catalog else None
        amount = _money(row.get('amount') if row.get('amount') is not None else row.get('quantity'))
        qty = max(1, int(amount))
        name = str(row.get('name') or 'Item')
        pack = row.get('mover_pack')
        if pack is None and re.search(r'\((?:CP|PBO)\)\s*$', name, re.I):
            pack = bool(re.search(r'\(CP\)\s*$', name, re.I))
        reference = row.get('reference_name')
        pending.append(InventoryEditItem(id=row.get('inventory_row_id') or str(uuid4()), job_id=job.id, room_id=room.id,
            catalog_item_id=cid,
            # The name as the list has it; a catalog item named exactly as the catalog names it takes the catalog's name.
            name=None if cid and not row.get('name_override') and name == catalog[cid].name else name,
            quantity=qty,
            unit_cuft=_money(row['unit_cuft']) if row.get('unit_cuft') else (_money(row.get('cuft')) / qty or Decimal('0.01')),
            unit_weight=_money(row['unit_weight']) if row.get('unit_weight') else _money(row.get('weight')) / qty,
            # An item the report lists with no units ships nothing.
            going=row.get('going') is not False and amount > 0, mover_pack=pack, sort_order=start + index,
            mover_pack_count=row.get('mover_pack_count'), manual=row.get('manual'),
            excluded_quantity=min(qty, max(0, int(row.get('excluded_quantity') or 0))),
            reference_name=str(reference)[:200] if reference else None,
            question_key=row.get('question_key'),
            selections=json.dumps(row.get('selections') or {}), set_id=row.get('set_id'), set_name=row.get('set_name')))
    ids = [item.id for item in pending]
    taken_items = {r.id for r in db.query(InventoryEditItem.id).filter(InventoryEditItem.id.in_(ids))} if ids else set()
    seen = set()
    for item in pending:
        if item.id in taken_items or item.id in seen:
            item.id = str(uuid4())
        if not item.question_key:
            item.question_key = item.id
        seen.add(item.id)
    db.flush()  # Rooms first, for databases that enforce foreign keys immediately.
    db.add_all(pending)
    db.flush()


def fill_inventory(job, rows, rooms, report_id, state, db):
    """Replace the job's whole inventory with these rows (a past report chosen again, or a move's saved inventory being
    moved into the tables); returns the job's editor state. Does not commit."""
    db.query(InventoryEditItem).filter_by(job_id=job.id).delete(synchronize_session=False)
    db.query(InventoryEditRoom).filter_by(job_id=job.id).delete(synchronize_session=False)
    db.flush()
    _write_rows(job, rows, rooms, db)
    return _editor_state(job, state, db, report_id)


def replace_report_items(job, rows, report_id, state, db):
    """A report ran: its items replace the previous report's items; the customer's own items stay as they are, and
    rooms only the previous report's items were in go. Returns the job's editor state. Does not commit."""
    old = db.query(InventoryEditItem).filter(InventoryEditItem.job_id == job.id, InventoryEditItem.manual.is_(False)).all()
    emptied = {row.room_id for row in old}
    for row in old:
        db.delete(row)
    db.flush()
    keep = db.query(InventoryEditRoom).filter_by(job_id=job.id).all()
    _write_rows(job, [dict(row, manual=False) for row in rows], [], db, keep_rooms=keep)
    used = {room_id for (room_id,) in db.query(InventoryEditItem.room_id).filter_by(job_id=job.id).distinct()}
    for room in keep:
        if room.id in emptied and room.id not in used:
            db.delete(room)
    db.flush()
    return _editor_state(job, state, db, report_id)


def lead_job_id(lead_id, db):
    """The job a lead's inventory belongs to: its customer page's job, else its first job."""
    from models import PublicMoveAccess
    return (db.query(PublicMoveAccess.job_id).filter_by(lead_id=lead_id).scalar()
            or db.query(LeadJob.id).filter_by(lead_id=lead_id).order_by(LeadJob.job_order).limit(1).scalar())


def report_inventory(job_id, details, db):
    """The current report's inventory in the form report history keeps it (and always kept it): the list as the
    customer has it, the units item answers took off, what ships, and the customer's rooms."""
    if not job_id or not active_report(details):
        # A report still running (or none) has no inventory of its own yet.
        return {'question_original_rows': [], 'question_excluded_items': [], 'spark_inventory_snapshot': [], 'manual_rooms': []}
    rows, rooms = list_rows(job_id, db)
    hidden = ('excluded_quantity', 'room_id')
    def plain(row):
        return {key: value for key, value in row.items() if key not in hidden}
    excluded = []
    for row in rows:
        count = row['excluded_quantity']
        if count:
            excluded.append(dict(plain(row), excluded_quantity=count) if count < row['amount'] else plain(row))
    source = details.get('report_source', 'liveswitch')
    if details.get('report_edited') or source == 'manual':
        listed = rooms
    elif source == 'combined':
        listed = [dict(room, items=[item for item in room['items'] if item.get('manual') is not False]) for room in rooms]
    else:
        listed = []
    listed = [dict(room, items=[plain(item) for item in room['items']]) for room in listed if room['items']]
    return {'question_original_rows': [plain(row) for row in rows], 'question_excluded_items': excluded,
            'spark_inventory_snapshot': [plain(row) for row in shipping_rows(job_id, db, rows)], 'manual_rooms': listed}
