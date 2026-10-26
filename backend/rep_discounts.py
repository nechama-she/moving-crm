"""Rep adjustments stored with the job, separately from calculated fees."""
import json
from decimal import Decimal


def apply(job, rows, volume=0):
    selection = json.loads(job.customer_packing_package or '{}')
    settings = selection.get('rep_discounts', {})
    snapshots = selection.get('rep_discount_bases', {})
    changed = bool(settings or snapshots)
    if not changed:
        return False
    for row in rows:
        previous = snapshots.pop(row.id, None)
        if previous and Decimal(str(row.total_cost or 0)) == Decimal(previous['total']) and Decimal(str(row.discount_amount or 0)) == Decimal(previous['discount']):
            row.total_cost = Decimal(previous['base'])
            row.discount_amount = Decimal(previous['base_discount'])
            row.description = previous['description']
        rule = settings.get(row.id)
        if not rule:
            continue
        base = max(Decimal(0), Decimal(str(row.total_cost or 0)))
        value = Decimal(str(rule['value']))
        amount = value if rule['type'] == 'amount' else base * value / 100
        if rule['type'] == 'total':
            amount = base - value
        if rule['type'] == 'rate':
            from math import ceil
            amount = base - value * Decimal(ceil(volume or 0))
        amount = min(base, max(Decimal(0), amount)).quantize(Decimal('.01'))
        original_discount = Decimal(str(row.discount_amount or 0))
        description = row.description or ''
        row.total_cost = base - amount
        row.discount_amount = original_discount + amount
        title = 'Discount' if rule['title'] == 'Rep discount' else rule['title']
        detail = f'{title}: -${amount:,.2f}'
        if rule['type'] == 'rate':
            detail += f' (new rate ${value:,.2f} per cu ft)'
        row.description = description + ' | ' + detail
        snapshots[row.id] = {'base': str(base), 'base_discount': str(original_discount), 'description': description,
                             'total': str(row.total_cost), 'discount': str(row.discount_amount)}
    selection['rep_discount_bases'] = snapshots
    serialized = json.dumps(selection)
    if serialized != job.customer_packing_package:
        job.customer_packing_package = serialized
    return changed
