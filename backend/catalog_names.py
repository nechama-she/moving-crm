"""Resolve current catalog names without changing saved inventory measurements."""
import re
from decimal import Decimal
from models import InventoryCatalogItem


def resolve_catalog_names(rows, db=None, catalog=None):
    if catalog is None:
        catalog = db.query(InventoryCatalogItem).all()
    by_id = {item.id: item for item in catalog}
    def normalize(name):
        return re.sub(r'[^a-z0-9]+', ' ', re.sub(r'\s*\((?:CP|PBO)\)\s*$', '', str(name), flags=re.I).casefold()).strip()
    result = []
    for source in rows:
        if not isinstance(source, dict):
            result.append(source)
            continue
        row = dict(source)
        item = by_id.get(row.get('catalog_item_id') or row.get('item_id'))
        if item is None and not row.get('name_override'):
            try:
                count = max(1, int(row.get('amount') or row.get('quantity') or 1))
                volume = Decimal(str(row['unit_cuft'])) if row.get('unit_cuft') is not None else Decimal(str(row.get('cuft'))) / count
                name = normalize(row.get('name', ''))
                matches = [candidate for candidate in catalog if not getattr(candidate, 'deleted', False)
                           and getattr(candidate, 'cuft', None) is not None and Decimal(str(candidate.cuft)) == volume
                           and (normalize(candidate.name) == name or re.sub(r' \d+ pieces?$', '', normalize(candidate.name)) == name)]
                item = matches[0] if len(matches) == 1 else None
            except (ValueError, TypeError, ArithmeticError):
                pass
        if item:
            row['catalog_item_id'] = row['item_id'] = item.id
            if not row.get('name_override'):
                old_name = str(row.get('name') or item.name)
                suffix = re.search(r'\s*\((?:CP|PBO)\)\s*$', old_name, re.I)
                row['reference_name'] = row.get('reference_name') or old_name
                row['name'] = (re.sub(r'\s*\((?:CP|PBO)\)\s*$', '', item.name, flags=re.I) + suffix.group(0)) if suffix else item.name
        result.append(row)
    return result
