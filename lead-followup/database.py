"""Database connection for lead-followup Lambda."""

import json
import os
from urllib.parse import quote_plus

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text

_engine = None


def _get_db_password() -> str:
    secret_arn = os.getenv("DB_SECRET_ARN", "")
    if secret_arn:
        try:
            sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
            resp = sm.get_secret_value(SecretId=secret_arn)
            secret = json.loads(resp["SecretString"])
            return secret.get("password", "")
        except (ClientError, Exception):
            pass
    return os.getenv("DB_PASSWORD", "")


def get_engine():
    global _engine
    if _engine is None:
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "moving_crm")
        user = os.getenv("DB_USER", "crm_admin")
        password = _get_db_password()
        url = f"postgresql://{user}:{quote_plus(password)}@{host}:{port}/{name}"
        if host != "localhost":
            url += "?sslmode=require"
        _engine = create_engine(url, pool_pre_ping=True, pool_size=2)
    return _engine


def get_company_timezones():
    """Get all companies with their timezone."""
    engine = get_engine()
    query = text("SELECT id, name, timezone FROM companies")
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()
        return [dict(r._mapping) for r in rows]


def get_leads_for_followup(window_start, window_end, limit=0, company_id=None):
    """Query leads from Postgres that were created in the given time window and have a smartmoving_id."""
    engine = get_engine()
    sql = """
        SELECT l.id, l.full_name, l.phone, l.email, l.smartmoving_id,
               l.created_at, l.created_time, l.status, c.name as company_name, c.phone as company_phone,
               c.aircall_number_id, c.timezone as company_timezone
        FROM leads l
        JOIN companies c ON l.company_id = c.id
        WHERE l.smartmoving_id IS NOT NULL
          AND l.created_time IS NOT NULL
          AND l.created_at >= :window_start
          AND l.created_at < :window_end
    """
    params = {"window_start": window_start, "window_end": window_end}
    if company_id:
        sql += " AND l.company_id = :company_id"
        params["company_id"] = company_id
    sql += " ORDER BY l.created_at DESC"
    if limit:
        sql += " LIMIT :limit"
        params["limit"] = limit

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]
