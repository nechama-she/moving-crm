from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user, require_dispatch_or_admin
from database import get_db
from models import Company, Job, User, UserCompany

router = APIRouter(prefix="/jobs", tags=["jobs"])

_VALID_STATUSES = {"scheduled", "in_progress", "completed", "cancelled"}


def _allowed_company_ids(user: User, db: Session) -> list[str]:
    """Returns the list of company IDs this user is authorised to see."""
    if user.role == "admin":
        return [c.id for c in db.query(Company).all()]
    return [
        uc.company_id
        for uc in db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
    ]


class JobCreate(BaseModel):
    company_id: str
    client_name: str
    move_date: date
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    origin_address: Optional[str] = None
    destination_address: Optional[str] = None
    notes: Optional[str] = None


class JobUpdate(BaseModel):
    client_name: Optional[str] = None
    move_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    origin_address: Optional[str] = None
    destination_address: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_jobs(
    start: date = Query(...),
    end: date = Query(...),
    company_ids: Optional[list[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    allowed = _allowed_company_ids(user, db)
    # Intersect requested companies with allowed ones — user cannot see beyond their scope
    filter_ids = [cid for cid in (company_ids or allowed) if cid in allowed]
    if not filter_ids:
        return []
    jobs = (
        db.query(Job)
        .filter(
            Job.company_id.in_(filter_ids),
            Job.move_date >= start,
            Job.move_date <= end,
        )
        .order_by(Job.move_date, Job.start_time)
        .all()
    )
    return [j.to_dict() for j in jobs]


@router.post("", status_code=201)
def create_job(
    body: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_dispatch_or_admin),
):
    allowed = _allowed_company_ids(user, db)
    if body.company_id not in allowed:
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    job = Job(
        company_id=body.company_id,
        client_name=body.client_name,
        move_date=body.move_date,
        start_time=body.start_time,
        end_time=body.end_time,
        origin_address=body.origin_address,
        destination_address=body.destination_address,
        notes=body.notes,
        created_by=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job.to_dict()


@router.put("/{job_id}")
def update_job(
    job_id: str,
    body: JobUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_dispatch_or_admin),
):
    allowed = _allowed_company_ids(user, db)
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.company_id not in allowed:
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    if body.status is not None and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job.to_dict()


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_dispatch_or_admin),
):
    allowed = _allowed_company_ids(user, db)
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.company_id not in allowed:
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    db.delete(job)
    db.commit()
