from fastapi import APIRouter

from db import leads_table

router = APIRouter(prefix="/api", tags=["System"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/debug/fields")
def debug_fields():
    """Temporary: returns field names from the first lead."""
    response = leads_table.scan(Limit=1)
    items = response.get("Items", [])
    if not items:
        return {"fields": []}
    return {"fields": list(items[0].keys())}
