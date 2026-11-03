"""Resolve current catalog names without changing saved inventory measurements."""
import re
from decimal import Decimal
from models import InventoryCatalogItem


def _catalog_for(rows, db):
    """Only the catalog items these rows name by id, in one query, read once per request. The whole
    catalog is read only when a row has to be matched by name: no id, an unknown id, or a deleted item."""
    from request_cache import cached
    ids = sorted({str(row.get('catalog_item_id') or row.get('item_id')) for row in rows
                  if isinstance(row, dict) and (row.get('catalog_item_id') or row.get('item_id'))})
    store = db.info.setdefault('request_cache', {}).setdefault('catalog-items', {})
    missing = [item_id for item_id in ids if item_id not in store]
    if missing:
        found = {item.id: item for item in db.query(InventoryCatalogItem).filter(InventoryCatalogItem.id.in_(missing))}
        store.update({item_id: found.get(item_id) for item_id in missing})
    by_id = {item_id: store[item_id] for item_id in ids if store[item_id] is not None}
    def needs_name_match(row):
        item = by_id.get(str(row.get('catalog_item_id') or row.get('item_id')))
        return getattr(item, 'deleted', False) or (item is None and not row.get('name_override'))
    if any(isinstance(row, dict) and needs_name_match(row) for row in rows):
        return cached(db, 'catalog', lambda: db.query(InventoryCatalogItem).all())
    return list(by_id.values())


def resolve_catalog_names(rows, db=None, catalog=None):
    if catalog is None:
        catalog = _catalog_for(rows, db)
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
        if item is not None and getattr(item, 'deleted', False):
            # Duplicate cleanup keeps old records for saved inventories. Reconnect
            # those references only when exactly one surviving name matches.
            surviving = [candidate for candidate in catalog if not getattr(candidate, 'deleted', False)
                         and normalize(candidate.name) == normalize(item.name)]
            if len(surviving) == 1:
                item = surviving[0]
        if item is None and not row.get('name_override'):
            exact = [candidate for candidate in catalog if not getattr(candidate, 'deleted', False)
                     and normalize(candidate.name) == normalize(row.get('name', ''))]
            if len(exact) == 1:
                item = exact[0]
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
