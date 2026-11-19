"""Pending schema changes for the existing production database.

Every deploy runs this. Each change here runs once: after a deploy has applied it, it is removed, so with nothing
pending a deploy does not touch the database.
"""
import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger("migrate")


def add_column(connection, table, column, kind):
    """Adds the column only when it is missing: the ALTER locks the whole table even when the column exists,
    which on a live database waits on (or deadlocks with) the requests using it."""
    if not connection.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
                              {'table': table, 'column': column}).first():
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {kind}'))


def migrate() -> None:
    # Pricing book versions: a book jobs still keep is retired, not changed, when edited. Remove after a deploy ran it.
    with engine.begin() as connection:
        add_column(connection, 'pricing_plans', 'retired_at', 'TIMESTAMP')
        add_column(connection, 'pricing_plans', 'replaced_by_id', 'VARCHAR(36) REFERENCES pricing_plans(id)')
        add_column(connection, 'lead_jobs', 'pricing_plan_at', 'TIMESTAMP')
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_pricing_plans_replaced_by_id ON pricing_plans (replaced_by_id)'))
        # A version keeps its rows' ids: these rows are keyed by their book and their id, no longer their id alone.
        for table in ('pricing_bulky_items', 'pricing_plan_pickup_areas', 'pricing_rates', 'pricing_rules', 'pricing_services',
                      'pricing_elevator_tiers', 'pricing_shuttle_areas'):
            key = connection.execute(text(
                "SELECT tc.constraint_name, array_agg(kcu.column_name::text ORDER BY kcu.column_name) FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name AND kcu.table_name = tc.table_name "
                "WHERE tc.table_name = :table AND tc.constraint_type = 'PRIMARY KEY' GROUP BY tc.constraint_name"), {'table': table}).first()
            if key and list(key[1]) != ['id', 'plan_id']:
                connection.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT {key[0]}'))
                connection.execute(text(f'ALTER TABLE {table} ADD PRIMARY KEY (plan_id, id)'))
                logger.info('%s keyed by book and id', table)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
