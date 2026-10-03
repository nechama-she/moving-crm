"""Seed catalog protection assignments from each book's own material rates."""
import json
import logging
import re
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from long_distance_packing import packing_card
from models import InventoryCatalogItem, PricingPlan, PricingService

VERSION = 'catalog_protection_v3'
logger = logging.getLogger('migrate')


def sized_family(material):
    return next((family for family in ('carton crate', 'shrink wrap')
                 if family in material.name.casefold()), None)


def fit_assignment(material, materials, volume):
    candidates = [m for m in materials if sized_family(m) == sized_family(material)
                  and m.capacity_unit == 'cuft' and m.capacity_kind == 'up_to'
                  and (m.capacity or m.box_capacity_cuft or 0) >= Decimal(volume)]
    if not candidates:
        return None
    capacity = min(m.capacity or m.box_capacity_cuft for m in candidates)
    matches = [m for m in candidates if (m.capacity or m.box_capacity_cuft) == capacity]
    return matches[0] if len(matches) == 1 else None


def protection_assignment(item, materials):
    """Return assignments and a review reason when a safe match is unavailable."""
    name = item.name.casefold()
    candidates, quantity, requirement = [], 1, 'required'
    if re.search(r'\bmattress\b|\bbox\s*springs?\b', name):
        size = re.search(r'\b(twin|single|full|double|queen|king)\b', name)
        if not size or re.search(r'\b(california|cal|xl|crib|futon|air|split)\b', name):
            return [], 'Confirm mattress / box-spring size and number of pieces'
        size = {'single': 'twin', 'double': 'full'}.get(size[0], size[0])
        candidates = [m for m in materials if m.mattress_size == size or
                      (re.search(r'\bmattress\s+(bag|cover)\b', m.name, re.I) and
                       re.search(r'\b' + size + r'\b', m.name, re.I))]
    elif re.search(r'\b(sofa|couch|sectional|loveseat|sofabed)\b', name) and not re.search(r'\btable\b', name):
        if re.search(r'\b(leather|vinyl|wicker)\b', name):
            return [], None
        pieces = re.search(r'\b(\d+)\s*[- ]?\s*(?:piece|section)s?\b', name)
        if pieces:
            quantity = int(pieces[1])
        if quantity < 1 or quantity > 100:
            return [], 'Confirm sofa section count'
        candidates = [m for m in materials if re.search(r'\bsofa\s+cover\b', m.name, re.I)]
        requirement = 'optional'
    else:
        category = None
        if re.search(r'\bmarble\b', name) or (re.search(r'\bglass\b', name) and re.search(r'\b(table|desk|cabinet|bookcase|shel(?:f|ves)|stand|nightstand|furniture|top)\b', name)):
            category = r'\bcarton\s+crate\b'
        elif re.search(r'\bmirror\b', name):
            if not re.fullmatch(r'(?:standing |full length )?mirror(?:\s+(?:full length|large|medium|small))*', name):
                return [], 'Confirm separate mirror dimensions'
            category = r'\bmirror\s+box\b'
        elif re.search(r'\b(picture|painting)s?\b', name) and not re.search(r'\b(box|bin)\b', name):
            category = r'\bpicture\s+box\b'
        if not category:
            return [], None
        candidates = [m for m in materials if re.search(category, m.name, re.I) and
                      m.capacity_unit == 'cuft' and m.capacity_kind == 'up_to' and
                      (m.capacity or m.box_capacity_cuft or 0) >= Decimal(item.cuft)]
        if candidates:
            capacity = min(m.capacity or m.box_capacity_cuft for m in candidates)
            candidates = [m for m in candidates if (m.capacity or m.box_capacity_cuft) == capacity]
    if len(candidates) != 1:
        return [], 'No unique matching material / size in this pricing book'
    return [{'item_id': item.id, 'material_id': candidates[0].id,
             'requirement': requirement, 'quantity': str(quantity)}], None


def seed_item_protection(connection):
    items = connection.execute(select(InventoryCatalogItem.__table__).where(
        InventoryCatalogItem.deleted.is_(False), InventoryCatalogItem.active.is_(True))).mappings().all()
    plans = PricingPlan.__table__
    services = PricingService.__table__
    for plan in connection.execute(select(plans.c.id, plans.c.item_materials)).mappings().all():
        saved = json.loads(plan['item_materials'] or '[]')
        saved = saved if isinstance(saved, dict) else {'rows': saved, 'defaults': []}
        if saved.get(VERSION):
            continue
        rows = connection.execute(select(services.c.comments).where(services.c.plan_id == plan['id'])).mappings().all()
        card = packing_card([SimpleNamespace(**row) for row in rows])
        if not card or not card.materials:
            continue
        additions, review = [], []
        current = saved.get('rows', [])
        rates = {material.id: material for material in card.materials}
        for item in items:
            assignments, reason = protection_assignment(SimpleNamespace(**item), card.materials)
            if assignments:
                material = rates[assignments[0]['material_id']]
                family = next(pattern for pattern in (r'mattress\s+(?:bag|cover)', r'sofa\s+cover', r'mirror\s+box', r'picture\s+box', r'carton\s+crate')
                              if re.search(pattern, material.name, re.I)) if not material.mattress_size else r'mattress\s+(?:bag|cover)'
                current = [row for row in current if not (row['item_id'] == item['id'] and
                           (row['material_id'] == material.id or
                            (row['material_id'] in rates and re.search(family, rates[row['material_id']].name, re.I))))]
            additions.extend(assignments)
            if reason:
                review.append({'item_id': item['id'], 'name': item['name'], 'reason': reason})
        saved['rows'] = current + additions
        configured = {row['item_id'] for row in saved['rows']}
        defaults = saved.get('defaults', [])
        sized_defaults = [row for row in defaults if row['material_id'] in rates and sized_family(rates[row['material_id']])]
        if sized_defaults:
            # Defaults previously applied only to items without any assignments.
            # Persist that same behavior as visible, individually sized rows.
            for item in items:
                if item['id'] not in configured and not re.search(r'\bbox(?:es)?\b', item['name'], re.I):
                    saved['rows'].extend({**row, 'item_id': item['id']} for row in defaults)
            saved['defaults'] = [row for row in defaults if row not in sized_defaults]
        by_id = {item['id']: item for item in items}
        fitted_rows = {}
        for row in saved['rows']:
            item, material = by_id.get(row['item_id']), rates.get(row['material_id'])
            if item and material and sized_family(material):
                fitted = fit_assignment(material, card.materials, item['cuft'])
                if fitted:
                    row = {**row, 'material_id': fitted.id}
                else:
                    review.append({'item_id': item['id'], 'name': item['name'], 'reason': 'No unique material size fits the item cubic feet'})
            key = row['item_id'], row['material_id']
            if key not in fitted_rows or row['requirement'] == 'required':
                fitted_rows[key] = row
        saved['rows'] = list(fitted_rows.values())
        saved[VERSION] = True
        saved['protection_review'] = review
        connection.execute(plans.update().where(plans.c.id == plan['id']).values(item_materials=json.dumps(saved)))
        logger.info('Packing protection book %s: %s assignments added; %s items need review', plan['id'], len(additions), len(review))
