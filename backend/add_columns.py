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

    # Convert leadgen_id unique index to regular index (skips if already done)
    is_unique = conn.execute(text(
        "SELECT indisunique FROM pg_index WHERE indexrelid = 'ix_leads_leadgen_id'::regclass"
    )).scalar()
    if is_unique:
        conn.execute(text("DROP INDEX ix_leads_leadgen_id"))
        conn.execute(text("CREATE INDEX ix_leads_leadgen_id ON leads (leadgen_id)"))
        conn.commit()
        print("OK: converted ix_leads_leadgen_id to non-unique")
    else:
        print("SKIP: ix_leads_leadgen_id already non-unique")

print("Done")

print("Done")
