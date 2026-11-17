"""Pending schema changes for the existing production database.

Every deploy runs this. Each change here runs once: after a deploy has applied it, it is removed, so with nothing
pending a deploy does not touch the database.
"""
import logging
import sys
from pathlib import Path

from sqlalchemy import text

# The shared libs folder beside backend, as the deployed package has it: the inventory step reads the customer page's
# estimate (routes.public_moves), which uses it.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from database import engine

logger = logging.getLogger("migrate")


def add_column(connection, table, column, kind):
    """Adds the column only when it is missing: the ALTER locks the whole table even when the column exists,
    which on a live database waits on (or deadlocks with) the requests using it."""
    if not connection.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
                              {'table': table, 'column': column}).first():
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {kind}'))


def migrate() -> None:
    # The out-of-area fee: its miles and amount on each pricing book, and each move's measured distance from the
    # company office to the pickup. All empty: no book has the fee until it is set. First, because the steps below
    # load moves with the model, which reads these columns. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'pricing_plans', 'out_of_area_miles', 'INTEGER')
        add_column(connection, 'pricing_plans', 'out_of_area_fee', 'NUMERIC(12, 2)')
        add_column(connection, 'lead_jobs', 'out_of_area_meters', 'INTEGER')
        add_column(connection, 'lead_jobs', 'out_of_area_revision', 'VARCHAR(64)')
    # Beside each signed estimate: the fingerprint of its move right after the inventory step below, for one that showed
    # as signed then. Empty for every other. Before that step, which sets it. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'estimate_signatures', 'migrated_state', 'VARCHAR(64)')
    # Customer Activity's own table, created once with every signature so far: removed signatures and changed estimates
    # are logged in it from now on. Remove after a deploy ran it.
    from customer_activity_log import create_activity_table
    with engine.begin() as connection:
        logger.info('Customer Activity table created with %s past signatures', create_activity_table(connection))
    # Payments' confirmation numbers: new CRM payments get one; existing payments keep none. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'lead_payments', 'confirmation_number', 'VARCHAR(12) UNIQUE')
    # When the customer link was emailed, and to which (masked) address. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'public_move_access', 'link_email_sent_at', 'TIMESTAMP')
        add_column(connection, 'public_move_access', 'link_email_hint', 'VARCHAR(255)')
    # The inventory tables become the inventory: each row records the units item answers took off, the report's own
    # name for it, and its question key. Then every move's saved inventory moves into the tables (approved estimates
    # untouched), and the report items table, which only mirrored it, goes. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'inventory_edit_items', 'excluded_quantity', 'INTEGER NOT NULL DEFAULT 0')
        add_column(connection, 'inventory_edit_items', 'reference_name', 'VARCHAR(200)')
        add_column(connection, 'inventory_edit_items', 'question_key', 'VARCHAR(200)')
    from database import SessionLocal
    from inventory_migration import migrate_inventories
    logger.info('Moved %s inventories into the inventory tables', migrate_inventories(SessionLocal))
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS lead_spark_inventory_items'))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
