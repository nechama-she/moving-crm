"""Match explicit item facts against configured material rules, never display names."""
from decimal import Decimal
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


def customer_material_quotes(materials, selections):
    result = []
    for id, values in selections.items():
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
