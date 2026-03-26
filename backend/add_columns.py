"""Add new columns to existing tables (idempotent)."""
from database import engine
from sqlalchemy import text

COLUMNS = [
    ("leads", "referral_source", "VARCHAR(100)"),
    ("leads", "service_type", "VARCHAR(50)"),
    ("leads", "smartmoving_id", "VARCHAR(100)"),
]

with engine.connect() as conn:
    for table, col, col_type in COLUMNS:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
        conn.commit()
        print(f"OK: {table}.{col}")

print("Done")

print("Done")
