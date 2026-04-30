import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import hash_password, require_admin
from database import get_db
from models import User, Company, UserCompany, AdminUnavailability, Lead
from routes.auth import validate_password_strength

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/users", tags=["Users"])


class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    role: str = "sales_rep"  # admin, sales_rep, dispatch


class AssignCompany(BaseModel):
    company_id: str


class AdminUnavailabilityCreate(BaseModel):
    admin_user_id: str
    start_at: str
    end_at: str
    reason: str = ""


def _parse_iso_datetime(value: str) -> datetime:
    # Accepts either 2026-04-29T12:00:00 or 2026-04-29T12:00:00Z
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@router.get("")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.name).all()
    return [u.to_dict() for u in users]


@router.post("")
def create_user(body: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role not in ("admin", "sales_rep", "dispatch"):
        raise HTTPException(status_code=400, detail="Invalid role")

    validate_password_strength(body.password)

    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.post("/{user_id}/companies")
def assign_company(
    user_id: str,
    body: AssignCompany,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    company = db.query(Company).filter(Company.id == body.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    existing = db.query(UserCompany).filter(
        UserCompany.user_id == user_id, UserCompany.company_id == body.company_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already assigned")

    db.add(UserCompany(user_id=user_id, company_id=body.company_id))
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.delete("/{user_id}/companies/{company_id}")
def remove_company(
    user_id: str,
    company_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    uc = db.query(UserCompany).filter(
        UserCompany.user_id == user_id, UserCompany.company_id == company_id
    ).first()
    if not uc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(uc)
    db.commit()
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role != "sales_rep":
        raise HTTPException(status_code=400, detail="Only sales reps can be deleted here")

    # Leave historical leads intact but clear current assignee before deleting rep.
    db.query(Lead).filter(Lead.assigned_to == user.id).update({Lead.assigned_to: None}, synchronize_session=False)

    db.query(UserCompany).filter(UserCompany.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.get("/admin-unavailability")
def list_admin_unavailability(
    admin_id: str = "",
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(AdminUnavailability)
    if admin_id:
        query = query.filter(AdminUnavailability.admin_user_id == admin_id)
    rows = query.order_by(AdminUnavailability.start_at.asc()).all()
    return [row.to_dict() for row in rows]


@router.post("/admin-unavailability")
def create_admin_unavailability(
    body: AdminUnavailabilityCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target_admin = db.query(User).filter(User.id == body.admin_user_id).first()
    if not target_admin or target_admin.role != "admin":
        raise HTTPException(status_code=400, detail="Target user must be an admin")

    try:
        start_at = _parse_iso_datetime(body.start_at)
        end_at = _parse_iso_datetime(body.end_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid datetime format")

    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    window = AdminUnavailability(
        admin_user_id=body.admin_user_id,
        start_at=start_at,
        end_at=end_at,
        reason=(body.reason or "").strip() or None,
        created_by=admin.id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)
    return window.to_dict()


@router.delete("/admin-unavailability/{window_id}")
def delete_admin_unavailability(
    window_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(AdminUnavailability).filter(AdminUnavailability.id == window_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Window not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
