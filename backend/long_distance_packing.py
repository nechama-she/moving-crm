"""Validated packing-card configuration stored with a long-distance pricing book."""
from decimal import Decimal
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

PACKING_CARD_PREFIX = '__ld_packing__:'
BOX_DEFAULTS = {
    'Book Box: 2 CU': ('books', 2), 'Small Box: 2 Cuft': ('any', 2),
    'Medium Box: 3.0 Cuft': ('any', 3), 'Large Box: 5 Cuft': ('any', 5),
    'Dish Box: 6.0 Cuft': ('dishes', 6),
    'Picture Box Standard 3.0cf: 3 CU': ('picture', 3),
    'Picture Box Large 6.0cf: 6 cuft': ('picture', 6),
    'Mirror Box: 6 cuft': ('mirror', 6), 'Wardrobe Box: 16 cuft': ('wardrobe', 16),
}

class RequiredBoxItem(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(default=0, ge=0, max_digits=10, decimal_places=2)
    labor_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    material_price: Decimal = Field(default=0, ge=0, max_digits=10, decimal_places=2)
    packing_material: Literal['plastic', 'cardboard'] = 'cardboard'

    @model_validator(mode='before')
    @classmethod
    def default_protection(cls, value):
        if isinstance(value, dict) and not value.get('packing_material'):
            value = {**value, 'packing_material': 'plastic' if re.search(
                r'\b(fabric|upholstered|sofa|couch|sectional|mattress|ottoman)\b',
                str(value.get('name', '')), re.IGNORECASE) else 'cardboard'}
        return value

    @model_validator(mode='after')
    def split_price(self):
        if self.labor_price is None:
            self.labor_price = self.price
        self.price = self.labor_price + self.material_price
        return self

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Required-box items need a name')
        return value.strip()

class MaterialRule(BaseModel):
    protection: Literal['fabric', 'fragile', 'both'] = 'fabric'
    item_type: str = Field(default='any', min_length=1, max_length=100)
    variant: str = Field(default='', max_length=100)
    measure: Literal['none', 'cubic_feet', 'screen_inches'] = 'none'
    minimum: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    maximum: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True
    unit: Literal['item', 'foot', 'sheet', 'roll'] = 'item'
    units_per_item: Decimal = Field(default=1, gt=0, max_digits=10, decimal_places=2)

    @model_validator(mode='after')
    def valid_range(self):
        if self.measure == 'none' and (self.minimum is not None or self.maximum is not None):
            raise ValueError('Choose a measurement for size limits')
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum or (self.minimum == self.maximum and not (self.minimum_inclusive and self.maximum_inclusive)):
                raise ValueError('Material size range is empty')
        if not self.item_type.strip():
            raise ValueError('Item type is required')
        return self


class MaterialRate(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    material_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    packing_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    unpacking_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    rule: MaterialRule | None = None
    box_capacity_cuft: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    capacity: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    capacity_unit: Literal['cuft', 'inches', 'sheets', 'feet', 'items', 'mattress_size'] = 'cuft'
    mattress_size: Literal['twin', 'full', 'queen', 'king'] | None = None
    capacity_kind: Literal['up_to', 'over'] = 'up_to'

    @model_validator(mode='before')
    @classmethod
    def automatic_box(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if value.get('capacity_unit') == 'mattress_size':
            if not value.get('mattress_size'):
                raise ValueError('Choose a mattress size')
            value.update(capacity=None, box_capacity_cuft=None)
            rule = dict(value.get('rule') or {})
            rule.update(protection='fabric', item_type='mattress', variant=value['mattress_size'],
                        measure='none', minimum=None, maximum=None)
            value['rule'] = rule
        if 'capacity' in value:
            capacity = value['capacity']
            unit = value.get('capacity_unit', 'cuft')
            value['box_capacity_cuft'] = capacity if unit == 'cuft' and value.get('capacity_kind', 'up_to') == 'up_to' else None
            if capacity is not None and unit in ('cuft', 'inches'):
                rule = dict(value.get('rule') or {'protection':'fragile', 'item_type':'any'})
                over = value.get('capacity_kind') == 'over'
                rule.update(measure='screen_inches' if unit == 'inches' else 'cubic_feet',
                            minimum=capacity if over else None, maximum=None if over else capacity,
                            minimum_inclusive=False if over else True, maximum_inclusive=True)
                value['rule'] = rule
        default = BOX_DEFAULTS.get(value.get('name'))
        if default and 'capacity' not in value and value.get('box_capacity_cuft') is None:
            value['box_capacity_cuft'] = default[1]
        if value.get('box_capacity_cuft') is not None and not value.get('rule'):
            value['rule'] = {'protection': 'fragile', 'item_type': default[0] if default else 'any'}
        return value

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Materials need a description')
        return value.strip()


class PackingCard(BaseModel):
    full: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    partial: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    unpacking: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    items: list[RequiredBoxItem] = Field(default_factory=list, max_length=500)
    materials: list[MaterialRate] = Field(default_factory=list, max_length=500)

    @field_validator('full', 'partial', 'unpacking', mode='before')
    @classmethod
    def blank_rate(cls, value):
        return None if value == '' else value

    @model_validator(mode='after')
    def unique_items(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('Required-box item IDs must be unique')
        if len({item.id for item in self.materials}) != len(self.materials):
            raise ValueError('Material IDs must be unique')
        return self


MATERIAL_FIELDS = ('name', 'material_price', 'packing_price', 'unpacking_price', 'capacity', 'capacity_unit',
                   'capacity_kind', 'mattress_size', 'box_capacity_cuft')
RULE_FIELDS = ('protection', 'item_type', 'variant', 'measure', 'minimum', 'maximum', 'minimum_inclusive',
               'maximum_inclusive', 'unit', 'units_per_item')


def plan_packing_card(plan):
    """The plan's packing rates and materials, read from pricing_packing and pricing_materials."""
    row = plan.packing
    if row is None:
        return None
    materials = []
    for material in sorted(row.materials, key=lambda material: material.sort_order):
        # Saved values were validated when saved; rebuilding them must not re-derive anything.
        rule = None if material.rule_protection is None else MaterialRule.model_construct(
            **{field: getattr(material, 'rule_' + field) for field in RULE_FIELDS})
        materials.append(MaterialRate.model_construct(id=material.material_id, rule=rule,
                                                      **{field: getattr(material, field) for field in MATERIAL_FIELDS}))
    return PackingCard.model_construct(full=row.full, partial=row.partial, unpacking=row.unpacking, items=[], materials=materials)


def _plain(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def packing_service_row(plan):
    """The card as the pricing API presents it: a service row holding its settings."""
    import json
    card = plan_packing_card(plan)
    if card is None:
        return None
    config = _plain(card.model_dump())
    for material in config['materials']:
        # Without its own capacity, a material's box capacity comes from the defaults when saved again.
        if material['capacity'] is None:
            del material['capacity']
    return {'id': f'packing:{plan.id}', 'name': 'Long-distance packing', 'rate_text': '',
            'comments': PACKING_CARD_PREFIX + json.dumps(config), 'sort_order': -1}


def save_packing_card(plan, card):
    """Replace the plan's packing rates and materials; None removes them. Legacy items are not kept."""
    from models import PricingPacking, PricingMaterial
    if card is None:
        plan.packing = None
        return
    row = plan.packing or PricingPacking()
    row.full, row.partial, row.unpacking = card.full, card.partial, card.unpacking
    existing = {material.material_id: material for material in row.materials}
    saved = []
    for position, material in enumerate(card.materials):
        target = existing.get(material.id) or PricingMaterial(material_id=material.id)
        for field in MATERIAL_FIELDS:
            setattr(target, field, getattr(material, field))
        for field in RULE_FIELDS:
            setattr(target, 'rule_' + field, getattr(material.rule, field) if material.rule else None)
        target.sort_order = position
        saved.append(target)
    row.materials[:] = saved
    plan.packing = row


def migrate_packing_cards(connection):
    """Move each plan's packing card from its pricing_services JSON row into tables, once."""
    from sqlalchemy import inspect, text
    from models import PricingPacking, PricingMaterial
    if inspect(connection).has_table(PricingPacking.__tablename__):
        return 0
    PricingPacking.__table__.create(connection)
    PricingMaterial.__table__.create(connection)
    moved = set()
    rows = connection.execute(text(
        "SELECT id, plan_id, comments FROM pricing_services WHERE comments LIKE :prefix ORDER BY plan_id, sort_order"),
        {'prefix': PACKING_CARD_PREFIX + '%'}).all()
    for service_id, plan_id, comments in rows:
        # Pricing used the first card of a plan; any later copies were never read.
        if plan_id not in moved:
            card = PackingCard.model_validate_json(comments[len(PACKING_CARD_PREFIX):])
            connection.execute(PricingPacking.__table__.insert().values(
                plan_id=plan_id, full=card.full, partial=card.partial, unpacking=card.unpacking))
            for position, material in enumerate(card.materials):
                connection.execute(PricingMaterial.__table__.insert().values(
                    plan_id=plan_id, material_id=material.id, sort_order=position,
                    **{field: getattr(material, field) for field in MATERIAL_FIELDS},
                    **{'rule_' + field: getattr(material.rule, field) if material.rule else None for field in RULE_FIELDS}))
            moved.add(plan_id)
        connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': service_id})
    return len(moved)


def packing_card(services):
    for service in services:
        if service.comments.startswith(PACKING_CARD_PREFIX):
            return PackingCard.model_validate_json(service.comments[len(PACKING_CARD_PREFIX):])
    return None
