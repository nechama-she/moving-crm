"""The master pricing book, and copying a book's values into another.

The master holds the default values new books start with. It belongs to no company and is inactive, so it never prices
a job; it is edited on the Pricing page like any other book.
"""
from uuid import uuid4

from sqlalchemy import and_, not_, text

MASTER_KEY = 'master'
PACKING_RATES = ('full', 'partial', 'unpacking')


def _kind(kind):
    return lambda table: table.c.kind == kind


def _discounts(table):
    return table.c.category.like('discount\\_%', escape='\\')


# Each card on the Pricing page and where it is kept: values on the book, or tables under it (with the rows of a
# shared table that are the card's).
PARTS = {
    'details': {'values': ('fuel_percent', 'admin_fee', 'price_valid_days')},
    'pickup': {'tables': ('pricing_plan_pickup_areas',)},
    'rates': {'tables': ('pricing_rates',)},
    'extraStops': {'tables': ('pricing_extra_stops',)},
    'elevator': {'tables': ('pricing_elevator', 'pricing_elevator_tiers')},
    'longCarry': {'tables': ('pricing_long_carry',)},
    'stairs': {'tables': ('pricing_stairs',)},
    'storage': {'tables': ('pricing_storage',)},
    'originFees': {'tables': ('pricing_mileage_fees', 'pricing_mileage_fee_rules', 'pricing_mileage_fee_zips'), 'rows': _kind('origin')},
    'deliveryFees': {'tables': ('pricing_mileage_fees', 'pricing_mileage_fee_rules', 'pricing_mileage_fee_zips'), 'rows': _kind('delivery')},
    'shuttle': {'tables': ('pricing_shuttle', 'pricing_shuttle_areas')},
    # Packing rates and materials share pricing_packing: its rates are the one card, its materials the other.
    'packing': {'packing': True},
    'materials': {'tables': ('pricing_materials',)},
    'itemMaterials': {'values': ('item_materials',)},
    'itemSelectors': {'values': ('item_selectors',)},
    'bulkyItems': {'tables': ('pricing_bulky_items',)},
    'discounts': {'tables': ('pricing_rules',), 'rows': _discounts},
    'services': {'tables': ('pricing_services', 'pricing_rules'), 'rows': lambda table: not_(_discounts(table)) if 'category' in table.c else None},
    'local': {'local': True},
}
# A new book starts with all of them but the pickup areas, which are its own.
NEW_BOOK_PARTS = tuple(part for part in PARTS if part != 'pickup')


def book_tables():
    """Every table under a pricing book, parents before their children: each holds its book's id in plan_id."""
    from models import Base
    tables = Base.metadata.tables
    ordered, under = [], {'pricing_plans'}
    while True:
        ready = [table for name, table in sorted(tables.items()) if name not in under
                 and any(key.column.table.name in under for key in table.foreign_keys)]
        if not ready:
            return ordered
        for table in ready:
            under.add(table.name)
            ordered.append(table)


def _where(table, plan_id, rows):
    condition = table.c.plan_id == plan_id
    extra = rows(table) if rows else None
    return condition if extra is None else and_(condition, extra)


def _ensure_packing(connection, packing, target_id):
    """Materials hang off the book's packing row: one with no rates is added when the book has none."""
    if connection.execute(packing.select().where(packing.c.plan_id == target_id)).first() is None:
        connection.execute(packing.insert(), {'plan_id': target_id})


def copy_book(connection, source_id, target_id, parts=NEW_BOOK_PARTS):
    """Replaces the target book's cards named in parts with a copy of the source's; its other cards stay."""
    unknown = set(parts) - set(PARTS)
    if unknown:
        raise ValueError(f'Unknown pricing book parts: {sorted(unknown)}')
    tables = {table.name: table for table in book_tables()}
    values = [name for part in parts for name in PARTS[part].get('values', ())]
    if values:
        row = connection.execute(text(f"SELECT {', '.join(values)} FROM pricing_plans WHERE id = :id"), {'id': source_id}).mappings().one()
        connection.execute(text(f"UPDATE pricing_plans SET {', '.join(f'{name} = :{name}' for name in values)} WHERE id = :id"),
                           {**row, 'id': target_id})
    if 'materials' in parts and connection.execute(tables['pricing_materials'].select().where(tables['pricing_materials'].c.plan_id == source_id)).first():
        _ensure_packing(connection, tables['pricing_packing'], target_id)
    if 'packing' in parts:
        packing = tables['pricing_packing']
        rates = connection.execute(packing.select().where(packing.c.plan_id == source_id)).mappings().first()
        if rates:
            _ensure_packing(connection, packing, target_id)
        connection.execute(packing.update().where(packing.c.plan_id == target_id),
                           {name: rates[name] if rates else None for name in PACKING_RATES})
    for part in parts:
        spec = PARTS[part]
        names = spec.get('tables', ())
        # Children first when clearing, parents first when copying.
        for name in reversed(names):
            connection.execute(tables[name].delete().where(_where(tables[name], target_id, spec.get('rows'))))
        for name in names:
            table = tables[name]
            rows = [dict(row) for row in connection.execute(table.select().where(_where(table, source_id, spec.get('rows')))).mappings()]
            own_id = [column.name for column in table.primary_key.columns] == ['id']
            for row in rows:
                row['plan_id'] = target_id
                if own_id:
                    row['id'] = str(uuid4())
            if rows:
                connection.execute(table.insert(), rows)
    if 'local' in parts:
        # Local pricing is a setting named after the book.
        local = connection.execute(text("SELECT value FROM app_settings WHERE key = :key"), {'key': f'local_pricing:{source_id}'}).scalar()
        connection.execute(text("DELETE FROM app_settings WHERE key = :key"), {'key': f'local_pricing:{target_id}'})
        if local is not None:
            connection.execute(text("INSERT INTO app_settings (key, value) VALUES (:key, :value)"),
                               {'key': f'local_pricing:{target_id}', 'value': local})


def master_id(connection):
    return connection.execute(text("SELECT id FROM pricing_plans WHERE source_key = :key"), {'key': MASTER_KEY}).scalar()
