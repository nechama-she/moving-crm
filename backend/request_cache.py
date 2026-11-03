"""Values read once per database session, so one request never asks the database the same thing twice.

Dropped on commit and rollback, and when a flush writes a row a cached value was read from.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session

# Rows whose writes make cached reads out of date: plans and local routes (plan match check),
# app settings (job routes) and catalog items (inventory names).
_SOURCES = ('PricingPlan', 'LocalPricingRoute', 'AppSetting', 'InventoryCatalogItem')


def cached(db, key, load):
    store = db.info.setdefault('request_cache', {})
    if key not in store:
        store[key] = load()
    return store[key]


def forget(db):
    db.info.pop('request_cache', None)


@event.listens_for(Session, 'after_commit')
@event.listens_for(Session, 'after_rollback')
@event.listens_for(Session, 'after_soft_rollback')
def _forget_after_transaction(session, *args):
    forget(session)


@event.listens_for(Session, 'after_flush')
def _forget_after_source_write(session, context):
    if any(type(row).__name__ in _SOURCES for row in (*session.new, *session.dirty, *session.deleted)):
        forget(session)
