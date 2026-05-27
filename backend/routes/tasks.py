import logging
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Lead, Task, User, UserCompany

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Tasks"])


class TaskStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"


class TaskType(str, Enum):
    call = "call"
    email = "email"
    text = "text"
    messenger = "messenger"
    instagram = "instagram"
    other = "other"


class TaskResponse(BaseModel):
    """A task attached to a lead."""
    id: str = Field(..., description="Task UUID")
    lead_id: str = Field(..., description="Lead this task belongs to")
    title: str = Field(..., description="Task subject / what needs to be done")
    due_date: str = Field("", description="YYYY-MM-DD, empty string if no due date")
    status: TaskStatus = Field(..., description="open | in_progress | done")
    task_type: TaskType = Field(..., description="call | email | text | messenger | instagram | other")
    created_by: str = Field(..., description="User UUID who created the task")
    created_at: str = Field(..., description="ISO 8601 timestamp")
    updated_at: str = Field(..., description="ISO 8601 timestamp")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "5b9c3e2a-f1b8-4d3f-9f1e-1a2b3c4d5e6f",
                "lead_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "title": "Call back about pricing",
                "due_date": "2026-06-02",
                "status": "open",
                "task_type": "call",
                "created_by": "u-123",
                "created_at": "2026-05-27T14:32:00+00:00",
                "updated_at": "2026-05-27T14:32:00+00:00",
            }
        }
    }


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
@router.get(
    "/leads/{lead_id}/tasks",
    response_model=List[TaskResponse],
    summary="List tasks for a lead",
)
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
    title: str = Field(..., min_length=1, description="Task subject")
    due_date: Optional[str] = Field(None, description="YYYY-MM-DD; omit or null for no due date")
    status: TaskStatus = Field(TaskStatus.open, description="Initial status")
    task_type: TaskType = Field(TaskType.other, description="Channel / activity type")


@router.post(
    "/leads/{lead_id}/tasks",
    status_code=201,
    response_model=TaskResponse,
    summary="Create a task on a lead",
)
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
        status=body.status.value,
        task_type=body.task_type.value,
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
    title: Optional[str] = Field(None, description="New subject")
    due_date: Optional[str] = Field(None, description="YYYY-MM-DD; empty string clears the due date")
    status: Optional[TaskStatus] = None
    task_type: Optional[TaskType] = None


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    summary="Update a task (partial)",
)
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
        task.status = body.status.value
    if body.task_type is not None:
        task.task_type = body.task_type.value

    db.commit()
    db.refresh(task)
    return task.to_dict()


# ---------------------------------------------------------------------------
# DELETE /api/tasks/{task_id}
# ---------------------------------------------------------------------------
@router.delete(
    "/tasks/{task_id}",
    status_code=204,
    summary="Delete a task",
)
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
