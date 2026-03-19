import logging

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Contact

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Leads"])


@router.get("/leads")
def get_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default=""),
    db: Session = Depends(get_db),
):
    query = db.query(Contact).order_by(Contact.created_time.desc())

    if search.strip():
        q = f"%{search.strip().lower()}%"
        query = query.filter(
            Contact.full_name.ilike(q)
            | Contact.leadgen_id.ilike(q)
            | Contact.phone.ilike(q)
            | Contact.email.ilike(q)
        )

    total = query.count()
    items = query.offset(offset).limit(limit).all()
    has_more = offset + limit < total

    return {
        "items": [c.to_dict() for c in items],
        "total": total,
        "has_more": has_more,
    }


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.leadgen_id == lead_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Lead not found")
    return contact.to_dict()
