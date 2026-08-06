import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from auth import hash_password, verify_password, create_access_token, get_current_user, require_impersonator
from database import get_db
from models import User, UserCompany

logger = logging.getLogger("moving-crm")

MIN_PASSWORD_LENGTH = 10

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def validate_password_strength(password: str) -> None:
    """Raise HTTPException if password is too weak."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_upper and has_lower and has_digit):
        raise HTTPException(status_code=400, detail="Password must contain uppercase, lowercase, and a digit")


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user.id, user.role)
    return LoginResponse(token=token, user=user.to_dict())


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    validate_password_strength(body.new_password)

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    db.refresh(user)
    return {"message": "Password changed successfully", "user": user.to_dict()}


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.post("/impersonate/{user_id}", response_model=LoginResponse)
def impersonate_user(
    user_id: str,
    actor: User = Depends(require_impersonator),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == actor.id:
        raise HTTPException(status_code=400, detail="You are already signed in as this user")
    if actor.role == "dispatch":
        if target.role != "foreman":
            raise HTTPException(status_code=403, detail="Dispatch can only impersonate foremen")
        if target.manager_dispatch_id != actor.id:
            raise HTTPException(status_code=403, detail="This foreman belongs to another dispatcher")

    token = create_access_token(target.id, target.role, impersonated_by=actor.id)
    logger.info("User %s started impersonating user %s", actor.id, target.id)
    return LoginResponse(token=token, user=target.to_dict())


@router.get("/impersonation-targets")
def list_impersonation_targets(
    actor: User = Depends(require_impersonator),
    db: Session = Depends(get_db),
):
    query = db.query(User).filter(User.id != actor.id)
    if actor.role == "dispatch":
        query = query.filter(User.role == "foreman", User.manager_dispatch_id == actor.id)
    return [item.to_dict() for item in query.order_by(User.name.asc()).all()]
