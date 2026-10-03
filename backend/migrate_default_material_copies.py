"""Undo complete optional-default bundles copied by the retired size migration."""
import json
import logging
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from long_distance_packing import packing_card
from models import PricingPlan, PricingService

VERSION = 'default_material_copies_cleanup_v1'
LEGACY_VERSIONS = tuple(f'item_material_sizes_v{i}' for i in (1, 2, 3))
logger = logging.getLogger('migrate')


def clean_default_copies(saved, materials=()):
    # A matching individual material can be an intentional override. Only undo
    # complete bundles in books touched by the migration that expanded defaults.
    if not isinstance(saved, dict) or saved.get(VERSION):
        return saved
    if not any(saved.get(version) for version in LEGACY_VERSIONS):
        return saved
    defaults = [row for row in saved.get('defaults', []) if row['requirement'] == 'optional']
    if len(defaults) != 5 or len({row['material_id'] for row in defaults}) != 5:
        return saved

    def signature(row):
        return row['material_id'], row['requirement'], Decimal(str(row['quantity']))

    bundle = {signature(row) for row in defaults}
    bundles = [bundle]
    # The retired migration also replaced Large with Small for small items.
    # Recognize that specific five-option bundle, never individual crates.
    names = {material.id: ' '.join(material.name.casefold().split()) for material in materials}
    large = [row for row in defaults if names.get(row['material_id']) == 'carton crate large']
    small = [id for id, name in names.items() if name == 'carton crate small']
    default_names = [names.get(row['material_id'], '') for row in defaults]
    if (len(bundle) == 5 and len(large) == len(small) == 1
            and 'carton crate medium' in default_names
            and 'carton crate extra large' in default_names
            and sum(name.startswith('shrink wrap') for name in default_names) == 2):
        replacement = {**large[0], 'material_id': small[0]}
        bundles.append((bundle - {signature(large[0])}) | {signature(replacement)})
    by_item = defaultdict(set)
    rows = saved.get('rows', [])
    for row in rows:
        by_item[row['item_id']].add(signature(row))
    copied = {}
    for item_id, signatures in by_item.items():
        matches = [candidate for candidate in bundles if candidate <= signatures]
        if len(matches) == 1:
            copied[item_id] = matches[0]
    def is_copy(row):
        return signature(row) in copied.get(row['item_id'], set())
    removed = [row for row in rows if is_copy(row)]
    return {
        **saved,
        'rows': [row for row in rows if not is_copy(row)],
        VERSION: {'removed_rows': removed},
    }


def cleanup_default_material_copies(connection):
    plans = PricingPlan.__table__
    services = PricingService.__table__
    count = 0
    for plan in connection.execute(select(plans.c.id, plans.c.item_materials).with_for_update()).mappings().all():
        saved = json.loads(plan['item_materials'] or '[]')
        if not isinstance(saved, dict) or saved.get(VERSION) or not any(saved.get(v) for v in LEGACY_VERSIONS):
            continue
        comments = connection.execute(select(services.c.comments).where(services.c.plan_id == plan['id'])).scalars()
        card = packing_card([SimpleNamespace(comments=value) for value in comments])
        cleaned = clean_default_copies(saved, card.materials if card else ())
        if cleaned == saved:
            continue
        removed = len(cleaned[VERSION]['removed_rows'])
        connection.execute(plans.update().where(plans.c.id == plan['id']).values(item_materials=json.dumps(cleaned)))
        logger.info('Removed %s copied optional defaults from pricing book %s', removed, plan['id'])
        count += removed
    return count
