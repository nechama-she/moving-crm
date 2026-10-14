"""Reconcile computed inventory without deleting and recreating unchanged rows."""
from collections import defaultdict
from decimal import Decimal
from models import LeadSparkInventoryItem


def sync_inventory_records(job_id, rows, db):
    current = db.query(LeadSparkInventoryItem).filter_by(job_id=job_id).order_by(LeadSparkInventoryItem.sort_order).all()
    by_values = defaultdict(list)
    for record in current:
        by_values[(record.name, record.amount, record.cuft)].append(record)
    used = set()
    pending = []
    for index, row in enumerate(rows):
        if row.get('going') is False:
            continue
        key = (str(row.get('name') or 'Item'), Decimal(str(row.get('amount') or 0)), Decimal(str(row.get('cuft') or 0)))
        candidates = by_values.get(key, [])
        record = candidates.pop(0) if candidates else None
        if record is not None:
            used.add(record.id)
        pending.append((index, key, record))
    for index, key, record in pending:
        if record is None:
            record = next((value for value in current if value.id not in used and value.sort_order == index), None)
            if record is None:
                record = LeadSparkInventoryItem(job_id=job_id)
                db.add(record)
            else:
                used.add(record.id)
        record.name, record.amount, record.cuft = key
        record.sort_order = index
    for record in current:
        if record.id not in used:
            db.delete(record)
