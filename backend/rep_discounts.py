"""Rep adjustments stored with the job, separately from calculated fees."""
import json
import re
from decimal import Decimal

# The lines priced together as the transportation package. The customer sees their subtotal; a discount set
# on it is saved on each of these lines, as their own discounts.
PACKAGE_LINES = ('Transportation charge', 'Fuel surcharge', 'Origin destination & administration Fee')


def package_lines(rows):
    return [row for row in rows if row.name in PACKAGE_LINES and row.source != 'smartmoving']


def cents(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'))


# The note a discount adds to its line's description: " | Name: -$12.34", with the new rate for a cu-ft rate discount.
DISCOUNT_NOTE = re.compile(r' \| [^|]*: -\$[\d,]+\.\d{2}(?: \(new rate [^)]*\))?')


def apply(job, rows, volume=0):
    selection = json.loads(job.customer_packing_package or '{}')
    settings = selection.get('rep_discounts', {})
    snapshots = selection.get('rep_discount_bases', {})
    package = package_lines(rows)
    changed = bool(settings or snapshots or any(cents(row.discount_amount) or DISCOUNT_NOTE.search(row.description or '')
                                                 for row in package))
    if not changed:
        return False
    for row in package:
        # The package carries one discount at most: each line starts again from its price before any discount, with
        # no discount and no discount notes, and only its current discount (if any) is applied below.
        snapshots.pop(row.id, None)
        row.total_cost = cents(row.subtotal)
        row.discount_amount = Decimal(0)
        row.description = DISCOUNT_NOTE.sub('', row.description or '')
    for row in rows:
        previous = snapshots.pop(row.id, None)
        # Compared in cents, as the database stores them: a line priced in fractions of a cent (a fuel percentage)
        # comes back rounded.
        if previous and cents(row.total_cost) == cents(previous['total']) and cents(row.discount_amount) == cents(previous['discount']):
            row.total_cost = Decimal(previous['base'])
            row.discount_amount = Decimal(previous['base_discount'])
            row.description = previous['description']
        rule = settings.get(row.id)
        if not rule:
            continue
        base = max(Decimal(0), cents(row.total_cost))
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
