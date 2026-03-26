import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config import get_config

cfg = get_config()


def get_database_url() -> str:
    # Config dict (from SSM) takes priority, then env vars, then defaults
    host = cfg.get("DB_HOST") or os.getenv("DB_HOST", "localhost")
    port = cfg.get("DB_PORT") or os.getenv("DB_PORT", "5432")
    name = cfg.get("DB_NAME") or os.getenv("DB_NAME", "moving_crm")
    user = cfg.get("DB_USER") or os.getenv("DB_USER", "crm_admin")
    password = cfg.get("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    return f"postgresql://{user}:{quote_plus(password)}@{host}:{port}/{name}"


engine = create_engine(get_database_url(), pool_pre_ping=True, pool_size=5)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
