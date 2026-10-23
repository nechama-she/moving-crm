import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Lead, Task, User
from routes.tasks import _can_see_lead
from fastapi import HTTPException

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Followups"])


@router.get("/leads/{lead_id}/followups")
def get_followups(lead_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead or not lead.smartmoving_id:
        return {"followups": []}
    if not _can_see_lead(user, lead, db):
        raise HTTPException(403, 'Access denied')
    rows = (
        db.query(Task)
        .filter(Task.lead_id == lead.id, Task.smartmoving_followup_id.isnot(None))
        .order_by(Task.due_at.asc())
        .all()
    )
    # Preserve this endpoint's response for existing clients; tasks own the data.
    return {"followups": [{
        'note_id': row.smartmoving_followup_id, 'smartmoving_id': lead.smartmoving_id,
        'type': row.smartmoving_followup_type, 'title': row.title,
        'assigned_to_id': row.smartmoving_assigned_to_id or '',
        'due_date_time': row.due_at.isoformat() if row.due_at else '',
        'completed_at_utc': row.completed_at.isoformat() if row.completed_at else '',
        'notes': row.notes, 'completed': row.status == 'done',
        'created_at': row.created_at.isoformat() if row.created_at else '',
    } for row in rows]}
