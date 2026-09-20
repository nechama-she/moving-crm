"""Validated packing-card configuration stored with a long-distance pricing book."""
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator

PACKING_CARD_PREFIX = '__ld_packing__:'

class RequiredBoxItem(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Required-box items need a name')
        return value.strip()

class PackingCard(BaseModel):
    full: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    partial: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    unpacking: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    items: list[RequiredBoxItem] = Field(default_factory=list, max_length=500)

    @field_validator('full', 'partial', 'unpacking', mode='before')
    @classmethod
    def blank_rate(cls, value):
        return None if value == '' else value

    @model_validator(mode='after')
    def unique_items(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('Required-box item IDs must be unique')
        return self


def packing_card(services):
    for service in services:
        if service.comments.startswith(PACKING_CARD_PREFIX):
            return PackingCard.model_validate_json(service.comments[len(PACKING_CARD_PREFIX):])
    return None
