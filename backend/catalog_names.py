"""Catalog names for inventory rows, without changing saved inventory measurements.

Rows are matched to catalog items by name only once, when a report runs (match_catalog_names). Every read after that
uses the catalog id a row was saved with (resolve_catalog_names); a row saved without one is a custom item and is
never looked up again.
"""
import re
from decimal import Decimal
from models import InventoryCatalogItem

PACK_SUFFIX = r'\s*\((?:CP|PBO)\)\s*$'


def _row_id(row):
    return row.get('catalog_item_id') or row.get('item_id')


def _catalog_by_ids(rows, db):
    """The catalog items these rows carry the ids of, in one query, read once per request."""
    ids = sorted({str(_row_id(row)) for row in rows if isinstance(row, dict) and _row_id(row)})
    store = db.info.setdefault('request_cache', {}).setdefault('catalog-items', {})
    missing = [item_id for item_id in ids if item_id not in store]
    if missing:
        found = {item.id: item for item in db.query(InventoryCatalogItem).filter(InventoryCatalogItem.id.in_(missing))}
        store.update({item_id: found.get(item_id) for item_id in missing})
    return {item_id: store[item_id] for item_id in ids if store[item_id] is not None}


def catalog_items(rows, db):
    """The catalog items the rows' ids point to, by id (from the same one query as their names)."""
    return _catalog_by_ids(rows, db)


def _named(row, item):
    """The row with its catalog item's id and current name; a custom name stays."""
    row['catalog_item_id'] = row['item_id'] = item.id
    if not row.get('name_override'):
        old_name = str(row.get('name') or item.name)
        suffix = re.search(PACK_SUFFIX, old_name, re.I)
        row['reference_name'] = row.get('reference_name') or old_name
        row['name'] = (re.sub(PACK_SUFFIX, '', item.name, flags=re.I) + suffix.group(0)) if suffix else item.name
    return row


def resolve_catalog_names(rows, db=None, catalog=None):
    """Each row's current catalog name, by the catalog id it was saved with. Never matches by name."""
    by_id = {item.id: item for item in catalog} if catalog is not None else _catalog_by_ids(rows, db)
    result = []
    for source in rows:
        if not isinstance(source, dict):
            result.append(source)
            continue
        row = dict(source)
        item = by_id.get(_row_id(row))
        result.append(_named(row, item) if item is not None else row)
    return result


def match_catalog_names(rows, db=None, catalog=None):
    """Only when a report runs: each row's catalog item, by its id or else by its name. A row with no match is saved
    as a custom item (name_override), so it is never matched by name again."""
    if catalog is None:
        catalog = db.query(InventoryCatalogItem).all()
    by_id = {item.id: item for item in catalog}
    def normalize(name):
        return re.sub(r'[^a-z0-9]+', ' ', re.sub(PACK_SUFFIX, '', str(name), flags=re.I).casefold()).strip()
    result = []
    for source in rows:
        if not isinstance(source, dict):
            result.append(source)
            continue
        row = dict(source)
        item = by_id.get(_row_id(row))
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
        if item is not None:
            _named(row, item)
        else:
            row['catalog_item_id'] = None
            row['name_override'] = True
        result.append(row)
    return result
