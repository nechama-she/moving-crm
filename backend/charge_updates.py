"""Update calculated charge rows in place, retaining IDs and creation dates."""
from models import LeadJobCharge


class ChargeUpdates:
    def __init__(self, db, existing, match_legacy_base=False, remove_missing=True):
        self.db = db
        self.existing = list(existing)
        self.by_id = {row.id: row for row in self.existing}
        self.used = set()
        self.match_legacy_base = match_legacy_base
        self.remove_missing = remove_missing

    def __getattr__(self, name):
        return getattr(self.db, name)

    def add(self, row):
        if not isinstance(row, LeadJobCharge):
            return self.db.add(row)
        current = self.by_id.get(row.id)
        # Older base charges had random IDs. Retain them when recalculating the same line.
        if current is None and self.match_legacy_base and row.sort_order < 1000:
            matches = [item for item in self.existing if item.id not in self.used
                       and item.sort_order < 1000 and item.name == row.name]
            current = next((item for item in matches if item.sort_order == row.sort_order),
                           matches[0] if len(matches) == 1 else None)
        if current is None:
            self.db.add(row)
            self.by_id[row.id] = row
            self.used.add(row.id)
            return
        if current.job_id != row.job_id:
            raise ValueError('Cannot update a charge belonging to another job')
        for field in ('name', 'description', 'sort_order', 'subtotal', 'discount_amount', 'total_cost'):
            setattr(current, field, getattr(row, field))
        self.used.add(current.id)

    def finish(self):
        # Repricing can make a charge free; retain its identity for later recalculations.
        # Customer deselection uses remove_missing=True to remove that selected service.
        for row in self.existing:
            if row.id not in self.used:
                if self.remove_missing:
                    self.db.delete(row)
                else:
                    row.subtotal = row.discount_amount = row.total_cost = 0
                    if (row.description or "").startswith("Calculation pending: "):
                        row.description = ""
        self.db.flush()
