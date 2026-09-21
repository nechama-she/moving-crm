"""Customer-entered room inventories use catalog values and the shared pricing flow."""
import json
import time
from decimal import Decimal
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from models import InventoryRoomType, InventoryCatalogItem, LeadLiveSwitch, LeadJob
from spark_history import remember_report, REPORT_KEYS, CONVERSATION_KEYS


class InventoryItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str
    quantity: int = Field(ge=1, le=999, strict=True)


class InventoryRoomInput(BaseModel):
    room_type_id: str
    name: str = Field(min_length=1, max_length=100)
    items: list[InventoryItemInput] = Field(max_length=500)


class ManualInventoryInput(BaseModel):
    request_id: UUID
    rooms: list[InventoryRoomInput] = Field(max_length=100)


def catalog(db):
    return {'rooms': [{'id': r.id, 'name': r.name} for r in db.query(InventoryRoomType).order_by(InventoryRoomType.sort_order).all()],
            'items': [{'id': r.id, 'name': r.name, 'description': r.description,
                       'cuft': float(r.cuft), 'weight': float(r.weight)}
                      for r in db.query(InventoryCatalogItem).filter_by(active=True).order_by(InventoryCatalogItem.name, InventoryCatalogItem.cuft).all()]}


def build_inventory(body, db, allow_empty=False):
    room_types = {r.id for r in db.query(InventoryRoomType).all()}
    ids = {item.item_id for room in body.rooms for item in room.items}
    items = {r.id: r for r in db.query(InventoryCatalogItem).filter(InventoryCatalogItem.id.in_(ids), InventoryCatalogItem.active.is_(True)).all()}
    if (not ids and not allow_empty) or set(items) != ids:
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
            row = {'item_id': item.id, 'room': room.name.strip(), 'name': item.name,
                   'amount': entry.quantity, 'cuft': float(volume), 'weight': float(mass),
                   'unit_cuft': float(item.cuft), 'unit_weight': float(item.weight)}
            rows.append(row)
            contents.append(row)
        rooms.append({'room_type_id': room.room_type_id, 'name': room.name.strip(), 'items': contents})
    return rooms, rows, float(cuft), float(weight)


def submit_inventory(body, access, db):
    from routes.liveswitch import apply_spark_results_to_lead
    rooms, rows, cuft, weight = build_inventory(body, db)
    job = db.query(LeadJob).filter_by(id=access.job_id).with_for_update().one()
    saved = db.get(LeadLiveSwitch, access.lead_id)
    details = json.loads(saved.details or '{}') if saved else {}
    report_id = 'manual-' + str(body.request_id)
    if any(row.get('last_spark_id') == report_id for row in details.get('spark_history', [])):
        if details.get('last_spark_id') != report_id:
            raise HTTPException(409, 'This list is already in your history. Select it there.')
        return apply_spark_results_to_lead(access.lead_id, '', db, expected_report_id=report_id)
    details['report_customer_packing'] = job.customer_packing
    details['report_customer_package'] = job.customer_packing_package
    remember_report(details)
    for key in REPORT_KEYS:
        details.pop(key, None)
    for key in CONVERSATION_KEYS:
        details[key] = ''
    details.update(last_spark_id=report_id, last_spark_status='completed', last_spark_at=int(time.time()),
                   report_list_body=body.model_dump(mode='json'), report_source='manual', manual_rooms=rooms, spark_inventory_snapshot=rows,
                   spark_extracted_cuft=cuft, spark_extracted_weight=weight, report_files=[],
                   report_conversation={}, spark_pricing_ready=False)
    remember_report(details)
    if not saved:
        saved = LeadLiveSwitch(lead_id=access.lead_id)
        db.add(saved)
    saved.details = json.dumps(details)
    job.customer_packing = job.customer_packing_package = None
    access.published_price = access.published_cuft = access.published_at = None
    db.commit()
    return apply_spark_results_to_lead(access.lead_id, '', db, expected_report_id=report_id)


def save_inventory_draft(body, access, db):
    rooms, rows, cuft, weight = build_inventory(body, db, allow_empty=True)
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
