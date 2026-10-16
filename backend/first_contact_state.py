"""Pending first contact: transactionally maintained state, no worker or timer."""
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from models import FirstContactState, FirstContactResolution


def install(connection):
    FirstContactState.__table__.create(connection, checkfirst=True)
    FirstContactResolution.__table__.create(connection, checkfirst=True)
    connection.execute(text("ALTER TABLE first_contact_resolutions ADD COLUMN IF NOT EXISTS evidence TEXT"))
    connection.execute(text("ALTER TABLE first_contact_resolutions ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ"))
    connection.execute(text("DROP TRIGGER IF EXISTS first_contact_changed ON leads"))
    connection.execute(text("DROP FUNCTION IF EXISTS sync_first_contact_state()"))


def contact_evidence(channel, item):
    from work_queue_rules import _epoch
    return {'channel': channel,
            'contacted_at': datetime.fromtimestamp(_epoch(item.get('timestamp')), timezone.utc).isoformat(),
            'record_id': str(item.get('call_id') or item.get('message_id') or item.get('id') or ''),
            'direction': str(item.get('direction') or ''),
            'sender': str(item.get('sales_name') or item.get('role') or ''),
            'client_identifier': str(item.get('phone_number') or item.get('user_id') or ''),
            'destination': str(item.get('company_number') or item.get('page_id') or ''),
            'message': str(item.get('message') or item.get('body') or item.get('text') or '')[:4000]}


def resolve(db, lead_id, occurred_at, evidence=None, source='contact_event'):
    import json
    # Serialize contact removal against the initial queue insertion.
    db.execute(text("SELECT id FROM leads WHERE id=:id FOR UPDATE"), {"id": lead_id})
    was_pending = db.get(FirstContactState, lead_id) is not None
    details = {**(evidence or {}), 'source': source, 'was_pending': was_pending}
    statement = insert(FirstContactResolution).values(
        lead_id=lead_id, contacted_at=occurred_at, evidence=json.dumps(details), recorded_at=datetime.now(timezone.utc))
    db.execute(statement.on_conflict_do_nothing(index_elements=[FirstContactResolution.lead_id]))
    return db.query(FirstContactState).filter_by(lead_id=lead_id).delete(synchronize_session=False)


def add_created_lead(lead_id, *, created_in_smartmoving_here=False):
    """Best effort after lead commit; never fail creation because of this queue."""
    import logging
    try:
        from database import SessionLocal
        from sqlalchemy.orm import joinedload
        from models import Lead, AppSetting
        from work_queue_rules import _smartmoving_created_at
        with SessionLocal() as db:
            lead = db.query(Lead).options(joinedload(Lead.company), joinedload(Lead.assignee)).filter_by(id=lead_id).first()
            if not lead or lead.priority != 0 or (lead.status or '').strip().lower() not in {'new', 'contacted', 'quoted', ''}:
                return
            if lead.company and (lead.company.name or '').strip().lower() == 'mirit great american':
                return
            created = _smartmoving_created_at(lead.created_time) if lead.created_time else lead.created_at
            if created is None:
                raise ValueError('Invalid source creation time')
            if not created.tzinfo:
                created = created.replace(tzinfo=timezone.utc)
            db.expunge_all()
        if lead.smartmoving_id and not created_in_smartmoving_here:
            from routes.unanswered_messages import has_first_contact
            contact = has_first_contact(lead, created, return_contact=True)
            if contact:
                with SessionLocal() as db:
                    resolve(db, lead_id, datetime.fromisoformat(contact['contacted_at']), contact, 'initial_check')
                    db.commit()
                return
        with SessionLocal() as db:
            # Serialize only the final write with contact events, never history reads.
            if not db.query(Lead.id).filter(Lead.id == lead_id).with_for_update().first():
                return
            if db.get(FirstContactResolution, lead_id) or db.get(AppSetting, 'first_contact.ignore:' + lead_id):
                return
            statement = insert(FirstContactState).values(lead_id=lead_id, waiting_since=created)
            db.execute(statement.on_conflict_do_nothing(index_elements=[FirstContactState.lead_id]))
            db.commit()
    except Exception:
        logging.getLogger('moving-crm').exception('Could not add saved lead %s to first-contact queue', lead_id)


def record_contact(db, channel, item):
    from work_queue_rules import _digits, _epoch
    from models import Lead, Company, User
    from sqlalchemy import func, or_
    occurred = datetime.fromtimestamp(_epoch(item.get('timestamp')), timezone.utc)
    if channel in {'calls', 'sms'}:
        if str(item.get('direction') or '').lower() not in ({'outbound'} if channel == 'calls' else {'outbound', 'sent'}):
            return 0
        if channel == 'sms' and (str(item.get('sales_name') or '').lower() in {'ai', 'assistant', 'bot'} or str(item.get('role') or '').lower() in {'ai', 'assistant', 'bot'}):
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
        query = db.query(Lead).filter(
            Lead.facebook_user_id == str(item['user_id']),
            Lead.company.has(Company.facebook_page_id == str(item['page_id'])))
    else:
        return 0
    removed = 0
    for lead in query.order_by(Lead.id).all():
        from work_queue_rules import _smartmoving_created_at
        created = _smartmoving_created_at(lead.created_time) if lead.created_time else lead.created_at
        if created is None:
            continue
        created = created.replace(tzinfo=timezone.utc) if not created.tzinfo else created
        if occurred >= created:
            removed += resolve(db, lead.id, occurred, contact_evidence(channel, item))
    return removed
