"""Validated packing-card configuration stored with a long-distance pricing book."""
from decimal import Decimal
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
    capacity_unit: Literal['cuft', 'inches', 'sheets', 'feet', 'items'] = 'cuft'
    capacity_kind: Literal['up_to', 'over'] = 'up_to'

    @model_validator(mode='before')
    @classmethod
    def automatic_box(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
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


def packing_card(services):
    for service in services:
        if service.comments.startswith(PACKING_CARD_PREFIX):
            return PackingCard.model_validate_json(service.comments[len(PACKING_CARD_PREFIX):])
    return None
