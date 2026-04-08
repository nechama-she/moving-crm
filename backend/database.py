import json
import os
from urllib.parse import quote_plus

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config import get_config

cfg = get_config()


def _get_db_password() -> str:
    """Read DB password from Secrets Manager (always current), falling back to SSM/env."""
    secret_arn = os.getenv("DB_SECRET_ARN", "")
    if secret_arn:
        try:
            sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
            resp = sm.get_secret_value(SecretId=secret_arn)
            secret = json.loads(resp["SecretString"])
            return secret.get("password", "")
        except (ClientError, Exception):
            pass
    return cfg.get("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")


def get_database_url() -> str:
    # Config dict (from SSM) takes priority, then env vars, then defaults
    host = cfg.get("DB_HOST") or os.getenv("DB_HOST", "localhost")
    port = cfg.get("DB_PORT") or os.getenv("DB_PORT", "5432")
    name = cfg.get("DB_NAME") or os.getenv("DB_NAME", "moving_crm")
    user = cfg.get("DB_USER") or os.getenv("DB_USER", "crm_admin")
    password = _get_db_password()
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
