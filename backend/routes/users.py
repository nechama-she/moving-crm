import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import hash_password, require_admin
from database import get_db
from models import User, Company, UserCompany

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/users", tags=["Users"])


class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    role: str = "sales_rep"  # admin, sales_rep, dispatch


class AssignCompany(BaseModel):
    company_id: str


@router.get("")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.name).all()
    return [u.to_dict() for u in users]


@router.post("")
def create_user(body: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role not in ("admin", "sales_rep", "dispatch"):
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
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
