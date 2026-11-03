"""How many units of an inventory box row the movers pack. The inventory row is the only record of it."""
import re


def row_quantity(row):
    try:
        return max(1, int(float(row.get('amount') or row.get('quantity') or 1)))
    except (TypeError, ValueError):
        return 1


def report_box_defaults(rows, full_packing):
    """LiveSwitch names its boxes "(CP)"; that is its label, not the customer's choice. A box from a report
    starts with the customer packing it (PBO), or the movers packing all of it with full packing."""
    for row in rows:
        name = str(row.get('name') or '')
        if isinstance(row, dict) and row.get('mover_pack_count') is None and re.search(r'\bbox(?:es)?\b|\bdish\s*pack\b', name, re.I):
            row.update(name=re.sub(r'\s*\((?:CP|PBO)\)\s*$', '', name, flags=re.I), mover_pack=None,
                       mover_pack_count=row_quantity(row) if full_packing else 0)
    return rows


def movers_pack_count(row):
    """Units of this row the movers pack: mover_pack_count, else the older all-or-nothing CP marking."""
    quantity = row_quantity(row)
    count = row.get('mover_pack_count')
    if count is not None:
        try:
            return max(0, min(quantity, int(count)))
        except (TypeError, ValueError):
            return 0
    if row.get('mover_pack') is True or (row.get('mover_pack') is None and re.search(r'\(CP\)\s*$', str(row.get('name') or ''), re.I)):
        return quantity
    return 0
