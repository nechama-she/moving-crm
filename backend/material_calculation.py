"""Match explicit item facts against configured material rules, never display names."""
from decimal import Decimal
import re
from uuid import uuid5, NAMESPACE_URL
from typing import Literal
from pydantic import BaseModel, Field
from long_distance_packing import MaterialRate


class MaterialItem(BaseModel):
    protection: Literal['fabric', 'fragile', 'both']
    item_type: str = Field(default='any', min_length=1, max_length=100)
    variant: str = Field(default='', max_length=100)
    cubic_feet: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    screen_inches: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    quantity: int = Field(default=1, ge=1, le=1000)


class CustomerMaterialItem(MaterialItem):
    label: str = Field(min_length=1, max_length=200)
    service: Literal['self', 'packing', 'materials'] = 'self'
    inventory_id: str | None = Field(default=None, max_length=100)


def inventory_material_options(inventory):
    result = []
    occurrences = {}
    for row in inventory:
        name = str(row.get('name') or '').strip()
        if not name or re.search(r'\bbins?\b', name, re.IGNORECASE):
            continue
        room = str(row.get('room') or '')
        text = name.casefold()
        item_type, variant, screen = 'any', '', None
        protection = 'fabric' if re.search(r'\b(fabric|upholstered|sofa|couch|sectional|mattress|ottoman)\b', text) else 'fragile'
        if 'mattress' in text:
            item_type = 'mattress'
            match = re.search(r'\b(twin|full|queen|king)\b', text)
            # Extended sizes must not silently use a standard-sized bag.
            if match and not re.search(r'\b(xl|california|cal)\b', text):
                variant = match.group(1)
        elif re.search(r'\b(tv|television)\b', text):
            item_type = 'tv'
            match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-?\s*(?:inch(?:es)?\b|in\b)|["\u2033])', text)
            if match:
                screen = float(match.group(1))
        else:
            for pattern, category in [(r'\b(sofa|couch|sectional)\b','sofa'),(r'\bbed frame\b','bed_frame'),
                                      (r'\bbooks?\b','books'),(r'\b(dishes|dishware)\b','dishes'),
                                      (r'\b(picture|painting)\b','picture'),(r'\bmirror\b','mirror'),(r'\bwardrobe\b','wardrobe')]:
                if re.search(pattern, text):
                    item_type = category
                    break
        try:
            quantity = min(1000, max(1, int(row.get('quantity') or row.get('amount') or 1)))
            volume = Decimal(str(row.get('unit_cuft') or 0))
            if not volume:
                volume = Decimal(str(row.get('cuft') or 0)) / quantity
            volume = float(volume) if volume.is_finite() and volume > 0 else None
        except (ValueError, TypeError, ArithmeticError):
            quantity, volume = 1, None
        key = str(row.get('id') or f'{room}:{name}')
        for index in range(quantity):
            occurrences[key] = occurrences.get(key, 0) + 1
            id = str(uuid5(NAMESPACE_URL, f'packing-inventory:{key}:{occurrences[key]}'))
            result.append({'id': id, 'room': room, 'name': name,
                          'label': f'{name} ({index+1} of {quantity})' if quantity > 1 else name,
                          'inventory_id': id, 'protection': protection, 'item_type': item_type,
                          'variant': variant, 'screen_inches': screen, 'cubic_feet': volume,
                          'quantity': 1, 'service': 'self'})
    return result


def customer_material_quotes(materials, selections, inventory=None):
    result = []
    for id, values in selections.items():
        if values.get('inventory_id') and inventory is not None:
            source = next((row for row in inventory if row['id'] == values['inventory_id']), None)
            if source is None:
                result.append({'id':id,'label':values['label'],'service':values.get('service','self'),
                               'status':'needs_review','issues':['Inventory item is no longer available'],
                               'lines':[],'packing_only':None,'packing_and_material':None})
                continue
            values = {**source, 'protection': values.get('protection', source['protection']),
                      'service': values.get('service', 'self')}
        item = CustomerMaterialItem.model_validate(values)
        result.append({'id': id, 'label': item.label, 'service': item.service,
                       **calculate_materials(materials, item)})
    return result


def calculate_materials(materials: list[MaterialRate], item: MaterialItem):
    selected = {}
    issues = []
    for protection in (['fabric', 'fragile'] if item.protection == 'both' else [item.protection]):
        candidates = []
        missing_variant = False
        for material in materials:
            rule = material.rule
            if rule is None or rule.protection not in (protection, 'both'):
                continue
            if rule.item_type.casefold() not in ('any', item.item_type.casefold()):
                continue
            if rule.variant and rule.variant.casefold() != item.variant.casefold():
                if not item.variant and rule.item_type.casefold() == item.item_type.casefold():
                    missing_variant = True
                continue
            candidates.append(material)
        if missing_variant:
            issues.append(f'{protection}: provide size / variant')
            continue
        # Specific item rules take precedence even when their size is missing.
        if candidates:
            specificity = lambda row: (row.rule.item_type != 'any', bool(row.rule.variant))
            best = max(map(specificity, candidates))
            candidates = [row for row in candidates if specificity(row) == best]
        matches = []
        missing = set()
        for material in candidates:
            rule = material.rule
            if material.box_capacity_cuft is not None and rule.measure != 'screen_inches':
                if item.cubic_feet is None:
                    missing.add('cubic_feet')
                    continue
                if item.cubic_feet > material.box_capacity_cuft:
                    continue
            if rule.measure != 'none':
                value = getattr(item, rule.measure)
                if value is None:
                    missing.add(rule.measure)
                    continue
                if rule.minimum is not None and (value < rule.minimum or (value == rule.minimum and not rule.minimum_inclusive)):
                    continue
                if rule.maximum is not None and (value > rule.maximum or (value == rule.maximum and not rule.maximum_inclusive)):
                    continue
            matches.append(material)
        if matches and all(row.box_capacity_cuft is not None for row in matches):
            smallest = min(row.box_capacity_cuft for row in matches)
            matches = [row for row in matches if row.box_capacity_cuft == smallest]
        if missing:
            issues.append(f"{protection}: provide {', '.join(sorted(missing))}")
        elif len(matches) != 1:
            issues.append(f"{protection}: {'overlapping material rules' if matches else 'no matching material rule'}")
        else:
            selected[matches[0].id] = matches[0]
    if issues:
        return {'status': 'needs_review', 'issues': issues, 'lines': [], 'packing_only': None, 'packing_and_material': None}
    lines = []
    for material in selected.values():
        quantity = material.rule.units_per_item * item.quantity
        money = lambda rate: (rate * quantity).quantize(Decimal('0.01'))
        lines.append({'material_id': material.id, 'name': material.name, 'quantity': quantity,
                      'unit': material.rule.unit, 'materials': money(material.material_price),
                      'packing': money(material.packing_price), 'unpacking': money(material.unpacking_price)})
    packing = sum((line['packing'] for line in lines), Decimal(0))
    return {'status': 'priced', 'issues': [], 'lines': lines, 'packing_only': packing,
            'packing_and_material': packing + sum((line['materials'] for line in lines), Decimal(0))}
