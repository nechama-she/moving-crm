"""Validate pricing row identities before changing a saved book."""
from fastapi import HTTPException


def prepare_row_updates(existing, incoming, identity_fields, required_fields):
    by_id = {row.id: row for row in existing}
    used = set()
    updates = []
    for row in incoming:
        row_id = getattr(row, 'id', None)
        match = by_id.get(row_id)
        if row_id and match is None:
            raise HTTPException(409, 'Pricing rows changed. Refresh the pricing book before saving.')
        if not row_id:
            matches = [item for item in existing if item.id not in used and all(
                getattr(item, key) == getattr(row, key) for key in identity_fields)]
            if len(matches) > 1:
                raise HTTPException(409, 'Refresh the pricing book before editing duplicate rows.')
            match = matches[0] if matches else None
        if match is not None:
            if match.id in used:
                raise HTTPException(422, 'Each pricing row must appear only once.')
            used.add(match.id)
        if any(not getattr(row, key).strip() for key in required_fields):
            if match is not None:
                raise HTTPException(422, 'Existing pricing rows need their required values. Use Remove to delete a row.')
            continue
        updates.append((match, row))
    return updates
