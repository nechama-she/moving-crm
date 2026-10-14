"""Install read-model tables and transactional invalidation; no data backfill."""
from sqlalchemy import text
from work_queue_models import QueueActivity, QueueCheckpoint, QueueDirty, QueueLead


def install(connection):
    for model in (QueueActivity, QueueCheckpoint, QueueDirty, QueueLead):
        model.__table__.create(connection, checkfirst=True)
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_work_queue_activity_source_time ON work_queue_activity (source, deleted, occurred_at)"))
    # PostgreSQL delivers notifications only after the writing transaction commits.
    # The rows remain durable if the listener is disconnected; startup drains them.
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION notify_work_queue() RETURNS trigger AS $$
        BEGIN
            IF current_setting('moving_crm.queue_worker', true) = 'on' THEN
                RETURN NULL;
            END IF;
            PERFORM pg_notify('work_queue_changed', '');
            RETURN NULL;
        END; $$ LANGUAGE plpgsql
    """))
    for table in ("work_queue_dirty", "work_queue_activity"):
        connection.execute(text(f"DROP TRIGGER IF EXISTS work_queue_notify ON {table}"))
        connection.execute(text(f"CREATE TRIGGER work_queue_notify AFTER INSERT OR UPDATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION notify_work_queue()"))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION notify_work_queue_recovery() RETURNS trigger AS $$
        BEGIN
            IF OLD.key LIKE 'ingestion_error:%' THEN
                PERFORM pg_notify('work_queue_changed', '');
            END IF;
            RETURN NULL;
        END; $$ LANGUAGE plpgsql
    """))
    connection.execute(text("DROP TRIGGER IF EXISTS work_queue_recovered ON work_queue_checkpoints"))
    connection.execute(text("CREATE TRIGGER work_queue_recovered AFTER DELETE ON work_queue_checkpoints FOR EACH ROW EXECUTE FUNCTION notify_work_queue_recovery()"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_queue_phone ON leads (right(regexp_replace(phone, '\\D', '', 'g'), 10))"))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION mark_work_queue_lead() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF ROW(OLD.full_name, OLD.phone, OLD.facebook_user_id, OLD.company_id,
                       OLD.assigned_to, OLD.status, OLD.priority, OLD.created_at, OLD.created_time)
                   IS NOT DISTINCT FROM
                   ROW(NEW.full_name, NEW.phone, NEW.facebook_user_id, NEW.company_id,
                       NEW.assigned_to, NEW.status, NEW.priority, NEW.created_at, NEW.created_time)
                THEN RETURN NEW; END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                INSERT INTO work_queue_dirty(lead_id) VALUES (OLD.id) ON CONFLICT (lead_id) DO UPDATE SET revision = work_queue_dirty.revision + 1;
                RETURN OLD;
            END IF;
            INSERT INTO work_queue_dirty(lead_id) VALUES (NEW.id) ON CONFLICT (lead_id) DO UPDATE SET revision = work_queue_dirty.revision + 1;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """))
    connection.execute(text("DROP TRIGGER IF EXISTS work_queue_lead_changed ON leads"))
    connection.execute(text("CREATE TRIGGER work_queue_lead_changed AFTER INSERT OR UPDATE OR DELETE ON leads FOR EACH ROW EXECUTE FUNCTION mark_work_queue_lead()"))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION mark_work_queue_directory() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF TG_TABLE_NAME = 'companies' THEN
                    IF ROW(OLD.name, OLD.phone, OLD.timezone, OLD.aircall_number_id, OLD.facebook_page_id)
                       IS NOT DISTINCT FROM
                       ROW(NEW.name, NEW.phone, NEW.timezone, NEW.aircall_number_id, NEW.facebook_page_id)
                    THEN RETURN NEW; END IF;
                ELSE
                    IF ROW(OLD.name, OLD.phone, OLD.aircall_number_id)
                       IS NOT DISTINCT FROM ROW(NEW.name, NEW.phone, NEW.aircall_number_id)
                    THEN RETURN NEW; END IF;
                END IF;
            END IF;
            IF TG_TABLE_NAME = 'companies' THEN
                INSERT INTO work_queue_dirty(lead_id)
                SELECT id FROM leads WHERE company_id = OLD.id ORDER BY id ON CONFLICT (lead_id) DO UPDATE SET revision = work_queue_dirty.revision + 1;
            ELSE
                INSERT INTO work_queue_dirty(lead_id)
                SELECT id FROM leads WHERE assigned_to = OLD.id ORDER BY id ON CONFLICT (lead_id) DO UPDATE SET revision = work_queue_dirty.revision + 1;
            END IF;
            RETURN OLD;
        END; $$ LANGUAGE plpgsql
    """))
    for table in ("companies", "users"):
        connection.execute(text(f"DROP TRIGGER IF EXISTS work_queue_directory_changed ON {table}"))
        connection.execute(text(f"CREATE TRIGGER work_queue_directory_changed AFTER UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION mark_work_queue_directory()"))
