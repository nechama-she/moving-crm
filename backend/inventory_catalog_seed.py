"""Idempotent initial catalog imported from Item Reference (1).csv."""
import json
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select
from models import InventoryRoomType, InventoryCatalogItem

ROOMS = ['Bedroom', 'Living Room', 'Dining Room', 'Kitchen', 'Bathroom', 'Office',
         'Garage', 'Outdoor', 'Basement', 'Attic', 'Laundry Room', 'Storage Room',
         'Family Room', 'Playroom', 'Hallway', 'Other']


def seed_inventory_catalog(connection):
    rooms = InventoryRoomType.__table__
    items = InventoryCatalogItem.__table__
    rooms.create(connection, checkfirst=True)
    items.create(connection, checkfirst=True)
    existing = set(connection.execute(select(rooms.c.id)).scalars())
    for index, name in enumerate(ROOMS):
        key = name.lower().replace(' ', '-')
        if key not in existing:
            connection.execute(rooms.insert().values(id=key, name=name, sort_order=index))
    existing = set(connection.execute(select(items.c.id)).scalars())
    records = json.loads((Path(__file__).parent / 'data/inventory_catalog.json').read_text(encoding='utf-8'))
    for row in records:
        if row['id'] not in existing:
            connection.execute(items.insert().values(**{**row, 'cuft': Decimal(row['cuft']), 'weight': Decimal(row['weight']), 'active': True}))
