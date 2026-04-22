"""Database connection for lead-followup Lambda."""

import json
import logging
import os
from urllib.parse import quote_plus

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

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


def get_due_followups(smartmoving_id: str | None = None):
    """Get followups that are due (not completed, due today) joined with lead info."""
    engine = get_engine()
    sql = """
        SELECT f.note_id, f.smartmoving_id, f.type, f.title, f.assigned_to_id,
               f.due_date_time, f.completed_at_utc, f.notes, f.completed,
               l.id as lead_id, l.full_name, l.phone, l.facebook_user_id,
               l.email, c.name as company_name, c.phone as company_phone,
               c.aircall_number_id, c.timezone as company_timezone
        FROM followups f
        JOIN leads l ON l.smartmoving_id = f.smartmoving_id::text
        JOIN companies c ON l.company_id = c.id
        WHERE f.completed = false
          AND f.due_date_time::date = CURRENT_DATE
    """
    params = {}
    if smartmoving_id:
        sql += "          AND f.smartmoving_id = :smartmoving_id\n"
        params["smartmoving_id"] = smartmoving_id
    sql += "        ORDER BY f.due_date_time DESC"
    logger.info("SQL get_due_followups (smartmoving_id=%s): %s", smartmoving_id, sql.strip())
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
        all_rows = [dict(r._mapping) for r in rows]
        logger.info("SQL get_due_followups response: %d rows", len(all_rows))
        for i, r in enumerate(all_rows):
            logger.info("  row %d: %s", i, r)
        # Group by smartmoving_id and return only the latest followup per lead
        seen = {}
        for row in all_rows:
            sm_id = row["smartmoving_id"]
            if sm_id not in seen:
                seen[sm_id] = row
        return list(seen.values())


def was_already_sent(smartmoving_id: str, message_type: str, channel: str) -> bool:
    """Check if a message was already sent (dedup)."""
    engine = get_engine()
    sql = text("""
        SELECT 1 FROM sent_messages
        WHERE smartmoving_id = :smartmoving_id
          AND message_type = :message_type
          AND channel = :channel
        LIMIT 1
    """)
    params = {"smartmoving_id": smartmoving_id, "message_type": message_type, "channel": channel}
    with engine.connect() as conn:
        row = conn.execute(sql, params).fetchone()
        found = row is not None
        logger.info("SQL was_already_sent(%s, %s, %s) => %s", smartmoving_id, message_type, channel, found)
        return found


def record_sent_message(smartmoving_id: str, message_type: str, channel: str):
    """Record that a message was sent (for dedup). Ignores duplicates."""
    engine = get_engine()
    sql = text("""
        INSERT INTO sent_messages (smartmoving_id, message_type, channel)
        VALUES (:smartmoving_id, :message_type, :channel)
        ON CONFLICT ON CONSTRAINT uq_sent_messages_dedup DO NOTHING
    """)
    params = {"smartmoving_id": smartmoving_id, "message_type": message_type, "channel": channel}
    logger.info("SQL record_sent_message(%s, %s, %s)", smartmoving_id, message_type, channel)
    with engine.connect() as conn:
        conn.execute(sql, params)
        conn.commit()
        logger.info("SQL record_sent_message: committed")


def sync_followup_from_smartmoving(
    smartmoving_id: str,
    note_id: str,
    followup_type: str,
    title: str,
    assigned_to_id: str,
    due_date_time_iso: str,
    notes: str,
    completed: bool,
) -> dict:
    """Sync refreshed followup data back to the local followups table."""
    engine = get_engine()
    sql = text(
        """
        UPDATE followups
        SET type = :followup_type,
            title = :title,
            assigned_to_id = :assigned_to_id,
            due_date_time = CAST(:due_date_time_iso AS timestamptz),
            notes = :notes,
            completed = :completed
        WHERE smartmoving_id::text = :smartmoving_id
          AND note_id = :note_id
        """
    )
    params = {
        "smartmoving_id": smartmoving_id,
        "note_id": str(note_id),
        "followup_type": followup_type,
        "title": title,
        "assigned_to_id": str(assigned_to_id),
        "due_date_time_iso": due_date_time_iso,
        "notes": notes,
        "completed": bool(completed),
    }
    logger.info("SQL sync_followup_from_smartmoving(%s, %s)", smartmoving_id, note_id)
    with engine.connect() as conn:
        result = conn.execute(sql, params)
        conn.commit()
        if result.rowcount == 0:
            return {"ok": False, "error": "followup_row_not_found"}
        return {"ok": True}


def get_sales_rep_number(name: str) -> str | None:
    """Look up a sales rep's Aircall number ID by name. Returns None if not found."""
    if not name:
        return None
    engine = get_engine()
    sql = text("SELECT aircall_number_id FROM sales_reps WHERE LOWER(TRIM(name)) = LOWER(TRIM(:name)) LIMIT 1")
    with engine.connect() as conn:
        row = conn.execute(sql, {"name": name}).fetchone()
        result = row[0] if row else None
        logger.info("SQL get_sales_rep_number(%s) => %s", name, result)
        return result
