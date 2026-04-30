import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import hash_password, require_admin
from database import get_db
from models import User, Company, UserCompany, AdminUnavailability, AdminUnavailabilityRep, RepAvailabilityWindow, Lead
from routes.auth import validate_password_strength

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/users", tags=["Users"])


class UserCreate(BaseModel):
    email: str
    name: str
    phone: str = ""
    password: str
    role: str = "sales_rep"  # admin, sales_rep, dispatch


class AssignCompany(BaseModel):
    company_id: str


class AdminUnavailabilityCreate(BaseModel):
    admin_user_id: str
    start_at: str
    end_at: str
    reason: str = ""
    rep_user_ids: List[str] = []


class RepAvailabilityCreate(BaseModel):
    rep_user_id: str
    start_at: str
    end_at: str
    reason: str = ""


class AdminUnavailabilityUpdate(BaseModel):
    start_at: str
    end_at: str
    reason: str = ""
    rep_user_ids: List[str] = []


class RepAvailabilityUpdate(BaseModel):
    rep_user_id: str
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

    if body.role == "sales_rep" and not (body.phone or "").strip():
        raise HTTPException(status_code=400, detail="Phone is required for sales reps")

    validate_password_strength(body.password)

    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        phone=(body.phone or "").strip(),
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
    window_ids = [r.id for r in rows]
    rep_rows = []
    if window_ids:
        rep_rows = (
            db.query(AdminUnavailabilityRep.window_id, User.id, User.name, User.email, User.phone)
            .join(User, User.id == AdminUnavailabilityRep.rep_user_id)
            .filter(AdminUnavailabilityRep.window_id.in_(window_ids))
            .all()
        )

    reps_by_window = {}
    for window_id, rep_id, rep_name, rep_email, rep_phone in rep_rows:
        reps_by_window.setdefault(window_id, []).append({
            "id": rep_id,
            "name": rep_name or "",
            "email": rep_email or "",
            "phone": rep_phone or "",
        })

    out = []
    for row in rows:
        item = row.to_dict()
        reps = reps_by_window.get(row.id, [])
        item["available_reps"] = reps
        item["available_rep_ids"] = [r["id"] for r in reps]
        out.append(item)
    return out


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

    rep_user_ids = [r for r in (body.rep_user_ids or []) if r]
    if rep_user_ids:
        rep_count = (
            db.query(User)
            .filter(User.id.in_(rep_user_ids), User.role == "sales_rep")
            .count()
        )
        if rep_count != len(set(rep_user_ids)):
            raise HTTPException(status_code=400, detail="All rep_user_ids must belong to sales reps")

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

    for rep_id in sorted(set(rep_user_ids)):
        db.add(AdminUnavailabilityRep(window_id=window.id, rep_user_id=rep_id))
    db.commit()

    window_data = window.to_dict()
    if rep_user_ids:
        reps = db.query(User).filter(User.id.in_(rep_user_ids)).order_by(User.name.asc()).all()
        window_data["available_reps"] = [
            {"id": r.id, "name": r.name, "email": r.email or "", "phone": r.phone or ""}
            for r in reps
        ]
        window_data["available_rep_ids"] = [r.id for r in reps]
    else:
        window_data["available_reps"] = []
        window_data["available_rep_ids"] = []
    return window_data


@router.delete("/admin-unavailability/{window_id}")
def delete_admin_unavailability(
    window_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(AdminUnavailability).filter(AdminUnavailability.id == window_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Window not found")
    db.query(AdminUnavailabilityRep).filter(AdminUnavailabilityRep.window_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.put("/admin-unavailability/{window_id}")
def update_admin_unavailability(
    window_id: str,
    body: AdminUnavailabilityUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(AdminUnavailability).filter(AdminUnavailability.id == window_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Window not found")

    try:
        start_at = _parse_iso_datetime(body.start_at)
        end_at = _parse_iso_datetime(body.end_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid datetime format")

    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    rep_user_ids = [r for r in (body.rep_user_ids or []) if r]
    if rep_user_ids:
        rep_count = (
            db.query(User)
            .filter(User.id.in_(rep_user_ids), User.role == "sales_rep")
            .count()
        )
        if rep_count != len(set(rep_user_ids)):
            raise HTTPException(status_code=400, detail="All rep_user_ids must belong to sales reps")

    row.start_at = start_at
    row.end_at = end_at
    row.reason = (body.reason or "").strip() or None

    db.query(AdminUnavailabilityRep).filter(AdminUnavailabilityRep.window_id == row.id).delete(synchronize_session=False)
    for rep_id in sorted(set(rep_user_ids)):
        db.add(AdminUnavailabilityRep(window_id=row.id, rep_user_id=rep_id))

    db.commit()
    db.refresh(row)

    window_data = row.to_dict()
    if rep_user_ids:
        reps = db.query(User).filter(User.id.in_(rep_user_ids)).order_by(User.name.asc()).all()
        window_data["available_reps"] = [
            {"id": r.id, "name": r.name, "email": r.email or "", "phone": r.phone or ""}
            for r in reps
        ]
        window_data["available_rep_ids"] = [r.id for r in reps]
    else:
        window_data["available_reps"] = []
        window_data["available_rep_ids"] = []
    return window_data


@router.get("/rep-availability")
def list_rep_availability(
    rep_id: str = "",
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(RepAvailabilityWindow)
    if rep_id:
        query = query.filter(RepAvailabilityWindow.rep_user_id == rep_id)
    rows = query.order_by(RepAvailabilityWindow.start_at.asc()).all()
    return [row.to_dict() for row in rows]


@router.post("/rep-availability")
def create_rep_availability(
    body: RepAvailabilityCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rep = db.query(User).filter(User.id == body.rep_user_id).first()
    if not rep or rep.role != "sales_rep":
        raise HTTPException(status_code=400, detail="Target user must be a sales rep")

    try:
        start_at = _parse_iso_datetime(body.start_at)
        end_at = _parse_iso_datetime(body.end_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid datetime format")

    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    window = RepAvailabilityWindow(
        rep_user_id=body.rep_user_id,
        start_at=start_at,
        end_at=end_at,
        reason=(body.reason or "").strip() or None,
        created_by=admin.id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)
    return window.to_dict()


@router.delete("/rep-availability/{window_id}")
def delete_rep_availability(
    window_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(RepAvailabilityWindow).filter(RepAvailabilityWindow.id == window_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Window not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.put("/rep-availability/{window_id}")
def update_rep_availability(
    window_id: str,
    body: RepAvailabilityUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(RepAvailabilityWindow).filter(RepAvailabilityWindow.id == window_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Window not found")

    rep = db.query(User).filter(User.id == body.rep_user_id).first()
    if not rep or rep.role != "sales_rep":
        raise HTTPException(status_code=400, detail="Target user must be a sales rep")

    try:
        start_at = _parse_iso_datetime(body.start_at)
        end_at = _parse_iso_datetime(body.end_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid datetime format")

    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    row.rep_user_id = body.rep_user_id
    row.start_at = start_at
    row.end_at = end_at
    row.reason = (body.reason or "").strip() or None
    db.commit()
    db.refresh(row)
    return row.to_dict()
