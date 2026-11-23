"""The work queue's Customer page and Customer chat cards (customer_page_states): one row per lead, its customer's
latest step on the customer page. Opening the page, asking for a code, verifying and chatting move the row forward,
never back; a text or call from the rep, or Ignore, clears it."""
from datetime import datetime, timezone

from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import load_only

from models import Company, CustomerPageState as Row, Lead, LeadJob, PublicMoveAccess, User, job_number
from realtime import publish_realtime_event

OPENED, VERIFIED, CHAT = 1, 2, 3
STATES = {OPENED: 'opened', VERIFIED: 'verified', CHAT: 'chat'}
EVENT = 'customer_page_state_changed'


def _upsert(db, statement, where=None):
    """Runs the insert of one row (values or a select), moving an existing row only to a later step (or where says).
    Returns the lead's id when the row changed, else None."""
    statement = statement.on_conflict_do_update(
        index_elements=[Row.lead_id],
        set_={column: getattr(statement.excluded, column) for column in ('job_id', 'state', 'code_channel', 'at')},
        where=Row.state < statement.excluded.state if where is None else where,
    ).returning(Row.lead_id)
    return db.execute(statement).scalar()


def _insert(db):
    # The Lambda packages leave out SQLAlchemy's sqlite dialect (buildspec.yml): it is imported only on sqlite.
    if db.get_bind().dialect.name == 'sqlite':
        from sqlalchemy.dialects import sqlite
        return sqlite.insert(Row)
    return postgresql.insert(Row)


def advance(db, access, state):
    """The customer's step on their page (access): moves the lead's row to it. Does not commit; returns whether it
    changed."""
    return _upsert(db, _insert(db).values(lead_id=access.lead_id, job_id=access.job_id, state=state,
                                          at=datetime.now(timezone.utc))) is not None


def request_code(db, access, channel):
    """The customer asked for a verification code ('sms' or 'email'): the lead's Opened row, or none yet, becomes
    Code requested. Never back from a later step. Does not commit; returns whether it changed."""
    statement = _insert(db).values(lead_id=access.lead_id, job_id=access.job_id, state=OPENED, code_channel=channel,
                                   at=datetime.now(timezone.utc))
    return _upsert(db, statement, where=(Row.state == OPENED) & Row.code_channel.is_(None)) is not None


def advance_to_chat(db, access_id, at):
    """The customer's chat message on the page whose access is access_id: the lead's row moves to Chat, read from
    the access in the same statement. Does not commit; returns the lead's id when the row changed."""
    source = (select(PublicMoveAccess.lead_id, PublicMoveAccess.job_id, literal(CHAT), literal(None), literal(at))
              .where(PublicMoveAccess.id == access_id))
    return _upsert(db, _insert(db).from_select(['lead_id', 'job_id', 'state', 'code_channel', 'at'], source))


def clear(db, condition):
    """Deletes the rows matching condition. Does not commit; the cleared leads wait in db.info for the event sent
    after the commit (cleared_event)."""
    removed = db.execute(delete(Row).where(condition).returning(Row.lead_id)).scalars().all()
    if removed:
        db.info.setdefault('customer_page_cleared', []).extend(removed)
    return removed


def cleared_event(db):
    """The event for the rows cleared since the last call, or None."""
    removed = db.info.pop('customer_page_cleared', None)
    return {'type': EVENT, 'row': None, 'lead_ids': removed} if removed else None


def items(db, lead_id=None):
    """The cards' rows, newest first (or the one lead's), with what the table shows."""
    query = (db.query(Row, Lead, LeadJob, Company.name, User.name)
             .join(Lead, Lead.id == Row.lead_id).join(LeadJob, LeadJob.id == Row.job_id)
             .outerjoin(Company, Company.id == func.coalesce(LeadJob.company_id, Lead.company_id))
             .outerjoin(User, User.id == Lead.assigned_to)
             .options(load_only(Lead.id, Lead.full_name, Lead.phone, Lead.number, Lead.smartmoving_id, Lead.quote_number),
                      load_only(LeadJob.id, LeadJob.job_order)))
    if lead_id is not None:
        query = query.filter(Row.lead_id == lead_id)
    return [{'lead_id': lead.id, 'job_id': job.id, 'at': row.at.isoformat(),
             'state': 'code_requested' if row.state == OPENED and row.code_channel else STATES[row.state],
             'code_channel': row.code_channel or '',
             'client': lead.full_name or '', 'phone': lead.phone or '', 'job_number': job_number(lead, job),
             'company': company or '', 'rep': rep or 'Unassigned',
             'smartmoving_id': str(lead.smartmoving_id or '').strip(), 'quote_number': str(lead.quote_number or '').strip()}
            for row, lead, job, company, rep in query.order_by(Row.at.desc())]


def row_event(db, lead_id):
    """After a commit: the event carrying the lead's row as it now stands."""
    rows = items(db, lead_id)
    return {'type': EVENT, 'row': rows[0] if rows else None, 'lead_ids': [] if rows else [lead_id]}


def publish_row(db, lead_id):
    publish_realtime_event(row_event(db, lead_id))


def chat_access_id(item):
    """The customer page access whose customer wrote this chat message, or None: BoxBot saves the customer's
    conversation as cp-<access_id> (the rep's is cp-rep-<access_id>), and its own replies with an assistant role."""
    user_id = str(item.get('user_id') or '').strip()
    if (str(item.get('platform') or '').strip().lower() != 'customer_page_bot' or not user_id.startswith('cp-')
            or user_id.startswith('cp-rep-') or str(item.get('role') or '').strip().lower() not in {'user', 'client', 'customer'}):
        return None
    return user_id[3:]
