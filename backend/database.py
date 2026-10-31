import json
import os
from urllib.parse import quote_plus

import boto3
import psycopg2
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from config import get_config

cfg = get_config()


def _get_db_password() -> str:
    """Read DB password from Secrets Manager (always current), falling back to env."""
    secret_arn = os.getenv("DB_SECRET_ARN", "")
    if secret_arn:
        try:
            sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
            resp = sm.get_secret_value(SecretId=secret_arn)
            secret = json.loads(resp["SecretString"])
            return secret.get("password", "")
        except (ClientError, Exception):
            pass
    # Env var: set by CodeBuild from Secrets Manager, or by hand for local dev
    return os.getenv("DB_PASSWORD", "")


_db_password: str | None = None


def _current_db_password(refresh: bool = False) -> str:
    """Cached DB password; refresh=True re-reads it after a rotation."""
    global _db_password
    if _db_password is None or refresh:
        _db_password = _get_db_password()
    return _db_password


def get_database_url(include_password: bool = True) -> str:
    # Config dict (from SSM) takes priority, then env vars, then defaults
    host = cfg.get("DB_HOST") or os.getenv("DB_HOST", "localhost")
    port = cfg.get("DB_PORT") or os.getenv("DB_PORT", "5432")
    name = cfg.get("DB_NAME") or os.getenv("DB_NAME", "moving_crm")
    user = cfg.get("DB_USER") or os.getenv("DB_USER", "crm_admin")
    credentials = f"{user}:{quote_plus(_current_db_password())}" if include_password else user
    url = f"postgresql://{credentials}@{host}:{port}/{name}"
    if host != "localhost":
        url += "?sslmode=require"
    return url


engine = create_engine(get_database_url(include_password=False), pool_pre_ping=True, pool_size=5)


@event.listens_for(engine, "do_connect")
def _connect_with_current_password(dialect, conn_rec, cargs, cparams):
    # Secrets Manager rotates the password; a warm Lambda would otherwise keep the old one.
    cparams["password"] = _current_db_password()
    try:
        return dialect.connect(*cargs, **cparams)
    except psycopg2.OperationalError as exc:
        if "password" not in str(exc):
            raise
        cparams["password"] = _current_db_password(refresh=True)
        return dialect.connect(*cargs, **cparams)


SessionLocal = sessionmaker(bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
