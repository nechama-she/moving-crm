"""Which tab of the customer page each fee belongs to (Elevator, Stairs, Packing services - Item protection...).

The one place the fees are grouped: the customer page groups its price lines by these tabs (the move details send each
line's tab in fee_tabs), and the PDFs group their fee rows by them too."""
import re

# The tabs in the page's order (its pricingSteps), each with its title; packing services has three parts.
TABS = {'stops:': 'Additional stops', 'elevator:': 'Elevator', 'access:': 'Truck access', 'stairs:': 'Stairs',
        'storage:': 'Storage', 'bulky:': 'Packing & crating', 'package:service': 'Packing services - Service',
        'package:protection': 'Packing services - Item protection', 'package:boxes': 'Packing services - Boxes'}


def fee_tab(name, data):
    """The tab of a fee line named name, from the move's details (the questions it has); None for a line on its own."""
    name = (name or '').lower()
    if data.get('extra_stops') is not None and (name == 'additional stops' or re.search(r'(?:extra|additional) (pickup|delivery) stop', name)):
        return 'stops:'
    if data.get('elevator') is not None and 'elevator' in name:
        return 'elevator:'
    if (data.get('long_carry') is not None or data.get('shuttle') is not None) and re.search(r'long carry|shuttle', name):
        return 'access:'
    if data.get('stairs') is not None and 'stairs' in name:
        return 'stairs:'
    if data.get('storage') is not None and 'storage' in name:
        return 'storage:'
    if any(f"{item['label']} {service['kind']}".lower() == name
           for item in data.get('packing_items') or [] for service in item.get('services') or []):
        return 'bulky:'
    package = data.get('packing_package')
    if package is not None:
        if re.fullmatch(r'full packing|partial packing|unpacking', name):
            return 'package:service'
        if any(f"{item['label']} Packing".lower() == name for item in package.get('box_items') or []):
            return 'package:boxes'
        if re.search(r'packing|boxing', name):
            return 'package:protection'
    return None


def fee_tabs(data):
    """Each price line's tab, by the line's id (lines on their own left out)."""
    charges = (data.get('estimate') or {}).get('charges') or []
    return {charge['id']: tab for charge in charges if charge.get('id') and (tab := fee_tab(charge.get('name'), data))}


def tab_discount_amounts(data, discounts):
    """What each section discount takes off its tab now: its amount, or its percent of the tab's lines as they show
    (after their own discounts), never more than the tab's total. By discount."""
    from decimal import Decimal
    tabs = fee_tabs(data)
    totals = {}
    for charge in (data.get('estimate') or {}).get('charges') or []:
        tab = tabs.get(charge.get('id'))
        if tab and not charge.get('pending'):
            totals[tab] = totals.get(tab, Decimal(0)) + Decimal(str(charge.get('total') or 0))
    result = {}
    for discount in discounts:
        total = totals.get(discount.tab, Decimal(0))
        value = Decimal(str(discount.value))
        amount = value if discount.kind == 'amount' else total * value / 100
        result[discount.id] = min(total, max(Decimal(0), amount)).quantize(Decimal('.01'))
    return result
