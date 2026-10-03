"""Remove packing assignments whose catalog item was removed."""
import json
from sqlalchemy import select
from models import InventoryCatalogItem, PricingPlan


def clean_configuration(raw, keep):
    saved = json.loads(raw or '[]')
    if isinstance(saved, list):
        return [row for row in saved if keep(row['item_id'])]
    return {**saved, **{key: [row for row in saved[key] if keep(row['item_id'])]
                       for key in ('rows', 'protection_review') if key in saved}}


def remove_item_assignments(db, ids):
    if not ids:
        return
    for plan in db.query(PricingPlan).with_for_update().all():
        cleaned = clean_configuration(plan.item_materials, lambda item_id: item_id not in ids)
        if cleaned != json.loads(plan.item_materials or '[]'):
            plan.item_materials = json.dumps(cleaned)


def cleanup_missing_assignments(connection):
    valid = set(connection.execute(select(InventoryCatalogItem.id).where(
        InventoryCatalogItem.deleted.is_(False))).scalars())
    plans = PricingPlan.__table__
    for plan in connection.execute(select(plans.c.id, plans.c.item_materials)).mappings().all():
        cleaned = clean_configuration(plan['item_materials'], lambda item_id: item_id in valid)
        if cleaned != json.loads(plan['item_materials'] or '[]'):
            connection.execute(plans.update().where(plans.c.id == plan['id']).values(item_materials=json.dumps(cleaned)))
