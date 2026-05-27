import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Lead, Task, User, UserCompany

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Tasks"])


def _can_see_lead(user: User, lead: Lead, db: Session) -> bool:
    """Return True if the user has access to the lead's company."""
    if user.role == "admin":
        return True
    return db.query(UserCompany).filter(
        UserCompany.user_id == user.id,
        UserCompany.company_id == lead.company_id,
    ).first() is not None


def _get_lead_or_404(lead_id: str, db: Session) -> Lead:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def _get_task_or_404(task_id: str, db: Session) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ---------------------------------------------------------------------------
# GET /api/leads/{lead_id}/tasks
# ---------------------------------------------------------------------------
@router.get("/leads/{lead_id}/tasks")
def list_tasks(
    lead_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_lead_or_404(lead_id, db)
    if not _can_see_lead(user, lead, db):
        raise HTTPException(status_code=403, detail="Access denied")
    tasks = (
        db.query(Task)
        .filter(Task.lead_id == lead_id)
        .order_by(Task.created_at.asc())
        .all()
    )
    return [t.to_dict() for t in tasks]


# ---------------------------------------------------------------------------
# POST /api/leads/{lead_id}/tasks
# ---------------------------------------------------------------------------
class TaskCreate(BaseModel):
    title: str
    due_date: Optional[str] = None   # YYYY-MM-DD or ""
    assigned_to: Optional[str] = None
    status: str = "open"


@router.post("/leads/{lead_id}/tasks", status_code=201)
def create_task(
    lead_id: str,
    body: TaskCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_lead_or_404(lead_id, db)
    if not _can_see_lead(user, lead, db):
        raise HTTPException(status_code=403, detail="Access denied")

    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    task = Task(
        lead_id=lead_id,
        title=title,
        due_date=(body.due_date or "").strip() or None,
        status=body.status if body.status in ("open", "in_progress", "done") else "open",
        assigned_to=body.assigned_to or None,
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task.to_dict()


# ---------------------------------------------------------------------------
# PATCH /api/tasks/{task_id}
# ---------------------------------------------------------------------------
class TaskUpdate(BaseModel):
    title: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    body: TaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_task_or_404(task_id, db)
    lead = _get_lead_or_404(task.lead_id, db)
    if not _can_see_lead(user, lead, db):
        raise HTTPException(status_code=403, detail="Access denied")

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        task.title = title
    if body.due_date is not None:
        task.due_date = body.due_date.strip() or None
    if body.status is not None:
        if body.status not in ("open", "in_progress", "done"):
            raise HTTPException(status_code=400, detail="Invalid status")
        task.status = body.status
    if body.assigned_to is not None:
        task.assigned_to = body.assigned_to or None

    db.commit()
    db.refresh(task)
    return task.to_dict()


# ---------------------------------------------------------------------------
# DELETE /api/tasks/{task_id}
# ---------------------------------------------------------------------------
@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_task_or_404(task_id, db)
    lead = _get_lead_or_404(task.lead_id, db)
    if not _can_see_lead(user, lead, db):
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(task)
    db.commit()
