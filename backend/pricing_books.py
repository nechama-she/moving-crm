"""The master pricing book, and copying a book's values into another.

The master holds the default values new books start with. It belongs to no company and is inactive, so it never prices
a job; it is edited on the Pricing page like any other book.
"""
from uuid import uuid4

from sqlalchemy import text

MASTER_KEY = 'master'
# The values on the book itself that are copied; its name, company and place in the list stay.
BOOK_VALUES = ('fuel_percent', 'admin_fee', 'price_valid_days', 'item_materials', 'item_selectors')
# A book's own area: kept when the master's values are copied into it.
PICKUP_AREAS = 'pricing_plan_pickup_areas'


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


def copy_book(connection, source_id, target_id, keep=(PICKUP_AREAS,)):
    """Replaces the target book's values with a copy of the source's: the values on the book, every table under it, and
    its local pricing. The tables named in keep stay as the target had them."""
    values = connection.execute(text(f"SELECT {', '.join(BOOK_VALUES)} FROM pricing_plans WHERE id = :id"),
                                {'id': source_id}).mappings().one()
    connection.execute(text(f"UPDATE pricing_plans SET {', '.join(f'{name} = :{name}' for name in BOOK_VALUES)} WHERE id = :id"),
                       {**values, 'id': target_id})
    tables = [table for table in book_tables() if table.name not in keep]
    # Children first when clearing, parents first when copying.
    for table in reversed(tables):
        connection.execute(table.delete().where(table.c.plan_id == target_id))
    for table in tables:
        rows = [dict(row) for row in connection.execute(table.select().where(table.c.plan_id == source_id)).mappings()]
        own_id = [column.name for column in table.primary_key.columns] == ['id']
        for row in rows:
            row['plan_id'] = target_id
            if own_id:
                row['id'] = str(uuid4())
        if rows:
            connection.execute(table.insert(), rows)
    # Local pricing is a setting named after the book.
    local = connection.execute(text("SELECT value FROM app_settings WHERE key = :key"), {'key': f'local_pricing:{source_id}'}).scalar()
    connection.execute(text("DELETE FROM app_settings WHERE key = :key"), {'key': f'local_pricing:{target_id}'})
    if local is not None:
        connection.execute(text("INSERT INTO app_settings (key, value) VALUES (:key, :value)"),
                           {'key': f'local_pricing:{target_id}', 'value': local})


def master_id(connection):
    return connection.execute(text("SELECT id FROM pricing_plans WHERE source_key = :key"), {'key': MASTER_KEY}).scalar()
