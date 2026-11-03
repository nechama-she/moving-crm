"""Test plans that keep the packing card as JSON on a service row and expose it as pricing_packing rows."""
from types import SimpleNamespace

from long_distance_packing import PACKING_CARD_PREFIX, PackingCard, MATERIAL_FIELDS, RULE_FIELDS


class PackingPlan(SimpleNamespace):
    @property
    def packing(self):
        row = next((service for service in getattr(self, 'services', []) if service.comments.startswith(PACKING_CARD_PREFIX)), None)
        if row is None:
            return None
        card = PackingCard.model_validate_json(row.comments[len(PACKING_CARD_PREFIX):])
        materials = [SimpleNamespace(material_id=material.id, sort_order=position,
                                     **{field: getattr(material, field) for field in MATERIAL_FIELDS},
                                     **{'rule_' + field: getattr(material.rule, field) if material.rule else None for field in RULE_FIELDS})
                     for position, material in enumerate(card.materials)]
        return SimpleNamespace(full=card.full, partial=card.partial, unpacking=card.unpacking, materials=materials)
