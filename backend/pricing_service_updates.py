"""Keep service identities stable so saved customer selections remain linked."""
from fastapi import HTTPException


def prepare_service_updates(existing, incoming):
    by_id = {row.id: row for row in existing}
    used = set()
    updates = []
    for row in incoming:
        id = row.id
        if id and id not in by_id:
            raise HTTPException(409, 'Pricing services changed. Refresh the pricing book before saving.')
        if id and id in used:
            raise HTTPException(422, 'Each pricing service must appear only once.')
        match = by_id.get(id)
        if not id:
            # Older clients omitted IDs. Reuse an unambiguous name match.
            matches = [item for item in existing if item.name.strip() == row.name.strip() and item.id not in used]
            if len(matches) > 1:
                raise HTTPException(409, 'Refresh the pricing book before editing duplicate service names.')
            match = matches[0] if matches else None
        if match is not None:
            used.add(match.id)
            if not row.name.strip():
                raise HTTPException(422, 'Existing pricing services need a name. Use Remove to delete a service.')
        if row.name.strip():
            updates.append((match, row))
    return updates
