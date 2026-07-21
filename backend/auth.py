"""Authentication utilities — JWT tokens + password hashing."""

import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User

load_dotenv()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "8"))
JWT_ISSUER = os.getenv("JWT_ISSUER", "moving-crm")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def _secret_key() -> str:
    """Return the JWT signing key.

    Never falls back to an insecure/committed default — token operations fail loudly
    if JWT_SECRET is not configured. (Password hashing does not call this, so DB
    migration/seed tooling can still import this module without the secret set.)
    """
    key = os.getenv("JWT_SECRET")
    if not key:
        raise RuntimeError(
            "JWT_SECRET is not set. Refusing to sign/verify tokens with an insecure "
            "default. Set JWT_SECRET (Secrets Manager / SSM SecureString in AWS, or "
            "backend/.env locally)."
        )
    return key


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode + validate a JWT (signature, expiry, issuer). Raises jwt.PyJWTError."""
    return jwt.decode(
        token,
        _secret_key(),
        algorithms=[ALGORITHM],
        issuer=JWT_ISSUER,
        options={"require": ["exp", "sub"]},
    )


def is_token_valid(token: str) -> bool:
    """Signature/expiry check with no DB hit — used by the global auth guard."""
    try:
        decode_access_token(token)
        return True
    except jwt.PyJWTError:
        return False


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency — extracts and validates JWT, returns User."""
    try:
        payload = decode_access_token(creds.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency — requires admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
