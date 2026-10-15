"""Pending first contact: transactionally maintained state, no worker or timer."""
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from models import FirstContactState, FirstContactResolution


def install(connection):
    FirstContactState.__table__.create(connection, checkfirst=True)
    FirstContactResolution.__table__.create(connection, checkfirst=True)
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION sync_first_contact_state() RETURNS trigger AS $$
        BEGIN
            IF NEW.priority = 0 AND lower(trim(coalesce(NEW.status, ''))) IN ('new','contacted','quoted','')
               AND NOT EXISTS (SELECT 1 FROM first_contact_resolutions WHERE lead_id = NEW.id)
               AND NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'first_contact.ignore:' || NEW.id)
               AND NOT EXISTS (SELECT 1 FROM companies WHERE id = NEW.company_id AND lower(trim(name)) = 'mirit great american')
            THEN
                INSERT INTO first_contact_states(lead_id, waiting_since) VALUES (NEW.id, NEW.created_at)
                ON CONFLICT (lead_id) DO NOTHING;
            ELSE
                DELETE FROM first_contact_states WHERE lead_id = NEW.id;
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """))
    connection.execute(text("DROP TRIGGER IF EXISTS first_contact_changed ON leads"))
    connection.execute(text("CREATE TRIGGER first_contact_changed AFTER INSERT OR UPDATE ON leads FOR EACH ROW EXECUTE FUNCTION sync_first_contact_state()"))
    # Existing leads are not backfilled. Lead inserts/updates maintain the queue.


def resolve(db, lead_id, occurred_at):
    # Serialize against lead updates so they cannot reinsert the pending row.
    db.execute(text("SELECT id FROM leads WHERE id=:id FOR UPDATE"), {"id": lead_id})
    statement = insert(FirstContactResolution).values(lead_id=lead_id, contacted_at=occurred_at)
    db.execute(statement.on_conflict_do_nothing(index_elements=[FirstContactResolution.lead_id]))
    return db.query(FirstContactState).filter_by(lead_id=lead_id).delete(synchronize_session=False)


def record_contact(db, channel, item):
    from work_queue_rules import _digits, _epoch
    from models import Lead, Company, User
    from sqlalchemy import func, or_
    occurred = datetime.fromtimestamp(_epoch(item.get('timestamp')), timezone.utc)
    if channel == 'calls':
        if str(item.get('direction') or '').lower() != 'outbound':
            return 0
        phone = _digits(item.get('phone_number'))
        destination = _digits(item.get('company_number'))
        if not phone or not destination:
            return 0
        def normalized(column):
            return func.right(func.regexp_replace(column, r'\D', '', 'g'), 10)
        query = db.query(Lead).filter(normalized(Lead.phone) == phone, or_(
            Lead.company.has(normalized(Company.phone) == destination),
            Lead.assignee.has(normalized(User.phone) == destination)))
    elif channel == 'messenger':
        role = str(item.get('role') or '').lower()
        sender = str(item.get('sales_name') or '').lower()
        direction = str(item.get('direction') or '').lower()
        if role in {'ai','assistant','bot','user','client','customer'} or sender in {'ai','assistant','bot'}:
            return 0
        if direction in {'draft','inbound','received'}:
            return 0
        if direction not in {'sent','outbound'} and role not in {'agent','human','sales','sales_rep','admin','business','page'}:
            return 0
        if not item.get('user_id') or not item.get('page_id'):
            return 0
        query = db.query(Lead).filter(func.trim(func.coalesce(Lead.phone,'')) == '',
            Lead.facebook_user_id == str(item['user_id']),
            Lead.company.has(Company.facebook_page_id == str(item['page_id'])))
    else:
        return 0
    removed = 0
    for lead in query.order_by(Lead.id).all():
        created = lead.created_at.replace(tzinfo=timezone.utc) if not lead.created_at.tzinfo else lead.created_at
        if occurred >= created:
            removed += resolve(db, lead.id, occurred)
    return removed
