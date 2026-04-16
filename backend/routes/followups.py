import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Lead, Followup, User

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Followups"])


@router.get("/leads/{lead_id}/followups")
def get_followups(lead_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead or not lead.smartmoving_id:
        return {"followups": []}
    rows = (
        db.query(Followup)
        .filter(Followup.smartmoving_id == lead.smartmoving_id)
        .order_by(Followup.due_date_time.asc())
        .all()
    )
    return {"followups": [r.to_dict() for r in rows]}
