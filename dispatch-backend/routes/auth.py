from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import verify_password, create_access_token, get_current_user, _DUMMY_HASH
from database import get_db
from models import User, UserCompany

router = APIRouter(prefix="/auth", tags=["auth"])
_limiter = Limiter(key_func=get_remote_address)


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
@_limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()

    # Always run bcrypt verify even when user not found — prevents timing-based
    # user enumeration (OWASP Authentication Cheat Sheet).
    hash_to_check = user.password_hash if user else _DUMMY_HASH
    valid = verify_password(body.password, hash_to_check)

    if not user or not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id, user.role)
    company_ids = [
        uc.company_id
        for uc in db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
    ]
    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "company_ids": company_ids,
        },
    }


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company_ids = [
        uc.company_id
        for uc in db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
    ]
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "company_ids": company_ids,
    }
