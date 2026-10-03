"""One-time correction of saved item material sizes; no runtime pricing changes."""
import json
import logging
import re
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from long_distance_packing import packing_card
from models import InventoryCatalogItem, PricingPlan, PricingService

VERSION = 'item_material_sizes_v2'
logger = logging.getLogger('migrate')


def family(material):
    for name in ('carton crate', 'shrink wrap', 'mirror box', 'picture box', 'bubble corrugated wrap'):
        if re.search(r'\b' + name.replace(' ', r'\s+') + r'\b', material.name, re.I):
            return name
    return None


def fit_material(material, materials, volume):
    category = family(material)
    if not category:
        return material
    matches = []
    for candidate in materials:
        if family(candidate) != category or candidate.capacity_unit != 'cuft':
            continue
        capacity = candidate.capacity or candidate.box_capacity_cuft
        if capacity is None:
            continue
        if candidate.capacity_kind == 'over':
            if volume > capacity:
                matches.append(((Decimal('Infinity'), -capacity), candidate))
        elif volume <= capacity:
            matches.append(((capacity, Decimal(0)), candidate))
    if not matches:
        return None
    best = min(rank for rank, _ in matches)
    winners = [candidate for rank, candidate in matches if rank == best]
    return winners[0] if len(winners) == 1 else None


def migrate_item_material_sizes(connection):
    catalog = {row['id']: row for row in connection.execute(select(InventoryCatalogItem.__table__).where(
        InventoryCatalogItem.deleted.is_(False))).mappings()}
    plans, services = PricingPlan.__table__, PricingService.__table__
    for plan in connection.execute(select(plans.c.id, plans.c.item_materials)).mappings().all():
        config = json.loads(plan['item_materials'] or '[]')
        config = config if isinstance(config, dict) else {'rows': config, 'defaults': []}
        if config.get(VERSION):
            continue
        rows = connection.execute(select(services.c.comments).where(services.c.plan_id == plan['id'])).mappings().all()
        card = packing_card([SimpleNamespace(**row) for row in rows])
        if not card or not card.materials:
            continue
        rates = {material.id: material for material in card.materials}
        assignments = config.get('rows', [])
        assigned = {row['item_id'] for row in assignments}
        defaults = config.get('defaults', [])
        # Defaults cannot have one correct size for every item. Save explicit
        # rows for items that currently fall back to these defaults.
        if any(row['material_id'] in rates and family(rates[row['material_id']]) for row in defaults):
            for item in catalog.values():
                if item['active'] and item['id'] not in assigned and not re.search(r'\bbox(?:es)?\b', item['name'], re.I):
                    assignments.extend({**row, 'item_id': item['id']} for row in defaults)
        updated = 0
        for row in assignments:
            item, material = catalog.get(row['item_id']), rates.get(row['material_id'])
            if item is None or material is None or not family(material):
                continue
            fitted = fit_material(material, card.materials, item['cuft'])
            if fitted is None:
                logger.warning('Material size needs review: book=%s item=%s material=%s cuft=%s', plan['id'], item['name'], material.name, item['cuft'])
                continue
            if any(other is not row and other['item_id'] == row['item_id'] and other['material_id'] == fitted.id for other in assignments):
                logger.warning('Material size conflict: book=%s item=%s material=%s', plan['id'], item['name'], fitted.name)
                continue
            updated += row['material_id'] != fitted.id
            row['material_id'] = fitted.id
        config['rows'] = assignments
        config[VERSION] = True
        connection.execute(plans.update().where(plans.c.id == plan['id']).values(item_materials=json.dumps(config)))
        logger.info('Corrected %s material sizes in pricing book %s', updated, plan['id'])
