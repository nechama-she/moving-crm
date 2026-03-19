import logging

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query

from db import leads_table, get_all_leads

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Leads"])


@router.get("/leads")
def get_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default=""),
):
    try:
        items = get_all_leads()

        if search.strip():
            q = search.strip().lower()
            search_fields = ["full_name", "leadgen_id", "phone_number", "email"]
            items = [
                item for item in items
                if any(q in str(item.get(f, "")).lower() for f in search_fields)
            ]

        page = items[offset : offset + limit]
        has_more = offset + limit < len(items)

        return {"items": page, "total": len(items), "has_more": has_more}
    except ClientError as e:
        logger.error("DynamoDB error: %s", e)
        raise HTTPException(status_code=502, detail="Could not fetch leads")


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str):
    try:
        response = leads_table.get_item(Key={"leadgen_id": lead_id})
        item = response.get("Item")
        if not item:
            raise HTTPException(status_code=404, detail="Lead not found")
        return item
    except ClientError as e:
        logger.error("DynamoDB error: %s", e)
        raise HTTPException(status_code=502, detail="Could not fetch lead")
