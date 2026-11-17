"""Customer Activity: each event on a customer page saved as its own row (customer_activity), so the work queue lists
what happened even after a signature is removed or the estimate changes."""
from uuid import uuid4

# What an event can be: its id in customer_activity_kinds, which holds each one's wording.
ESTIMATE_SIGNED, BILL_OF_LADING_SIGNED, ESTIMATE_SIGNATURE_REMOVED, ESTIMATE_CHANGED = 1, 2, 3, 4
KINDS = {ESTIMATE_SIGNED: 'Signed the estimate', BILL_OF_LADING_SIGNED: 'Signed the Bill of Lading',
         ESTIMATE_SIGNATURE_REMOVED: 'Removed the estimate signature',
         ESTIMATE_CHANGED: 'Changed the estimate: needs signing again'}


def record(db, lead_id, job_id, kind_id, actor='', by_rep=False, spot=None):
    """Adds one event; returns its id, for the CRM's notice. Does not commit."""
    from models import CustomerActivity
    activity_id = str(uuid4())
    db.add(CustomerActivity(id=activity_id, lead_id=lead_id, job_id=job_id, kind_id=kind_id, actor=(actor or '')[:200],
                            by_rep=bool(by_rep), spot=spot))
    return activity_id


def activity_items(db, since=None, activity_id=None, limit=200):
    """Customer Activity's rows, newest first: the last days (since), or the one event (activity_id)."""
    from bill_of_lading_pdf import SIGN_SPOTS
    from models import Company, CustomerActivity, CustomerActivityKind, Lead, LeadJob, job_number
    query = (db.query(CustomerActivity, CustomerActivityKind.label, Lead, LeadJob, Company.name)
             .join(CustomerActivityKind, CustomerActivityKind.id == CustomerActivity.kind_id)
             .join(Lead, Lead.id == CustomerActivity.lead_id).join(LeadJob, LeadJob.id == CustomerActivity.job_id)
             .outerjoin(Company, Company.id == LeadJob.company_id))
    if activity_id is not None:
        query = query.filter(CustomerActivity.id == activity_id)
    if since is not None:
        query = query.filter(CustomerActivity.created_at >= since)
    return [{'id': activity.id, 'kind_id': activity.kind_id, 'label': label, 'spot': activity.spot, 'spots': SIGN_SPOTS, 'lead_id': lead.id,
             'client': lead.full_name or '', 'job_id': job.id, 'job_number': job_number(lead, job), 'company': company or '',
             'actor': activity.actor, 'by_rep': activity.by_rep, 'at': activity.created_at.isoformat() + 'Z'}
            for activity, label, lead, job, company in query.order_by(CustomerActivity.created_at.desc()).limit(limit)]


def publish(db, lead_id, activity_id):
    """After the event is committed: the CRM's open pages show it (the work queue's list, and admins' notice)."""
    from realtime import publish_realtime_event
    items = activity_items(db, activity_id=activity_id, limit=1)
    publish_realtime_event({'type': 'customer_activity', 'lead_id': lead_id, 'activity': items[0] if items else None})


def log_estimate_changed(db, lead, job, by_rep):
    """The page found its signed estimate changed: logged once per signing, by the customer, or the rep the lead is
    assigned to. Commits a new event, and tells the CRM."""
    from models import CustomerActivity, EstimateSignature, User
    signed_at = (db.query(EstimateSignature.signed_at)
                 .filter(EstimateSignature.lead_id == lead.id, EstimateSignature.job_id == job.id, EstimateSignature.signed_at.isnot(None))
                 .order_by(EstimateSignature.signed_at.desc()).limit(1).scalar())
    if signed_at is None:
        return
    logged = (db.query(CustomerActivity.id)
              .filter(CustomerActivity.job_id == job.id, CustomerActivity.kind_id == ESTIMATE_CHANGED,
                      CustomerActivity.created_at >= signed_at).first())
    if logged is not None:
        return
    rep = db.get(User, lead.assigned_to) if by_rep and lead.assigned_to else None
    activity_id = record(db, lead.id, job.id, ESTIMATE_CHANGED, (rep.name if rep else '') if by_rep else lead.full_name, by_rep)
    db.commit()
    publish(db, lead.id, activity_id)


def create_activity_table(connection):
    """Once: the tables, the kinds with their wording, and every signature saved so far, so Customer Activity lists what
    it listed before."""
    from sqlalchemy import inspect, select
    from models import BillOfLadingSignature, CustomerActivity, CustomerActivityKind, EstimateSignature
    if inspect(connection).has_table(CustomerActivity.__tablename__):
        return 0
    CustomerActivityKind.__table__.create(connection)
    connection.execute(CustomerActivityKind.__table__.insert(), [dict(id=kind_id, label=label) for kind_id, label in KINDS.items()])
    CustomerActivity.__table__.create(connection)
    rows = []
    for row in connection.execute(select(EstimateSignature.lead_id, EstimateSignature.job_id, EstimateSignature.signer_name,
                                         EstimateSignature.signed_at).where(EstimateSignature.signed_at.isnot(None))):
        rows.append(dict(id=str(uuid4()), lead_id=row.lead_id, job_id=row.job_id, kind_id=ESTIMATE_SIGNED,
                         actor=row.signer_name or '', by_rep=False, spot=None, created_at=row.signed_at))
    for row in connection.execute(select(BillOfLadingSignature.lead_id, BillOfLadingSignature.job_id, BillOfLadingSignature.signer_name,
                                         BillOfLadingSignature.spot, BillOfLadingSignature.signed_at)):
        rows.append(dict(id=str(uuid4()), lead_id=row.lead_id, job_id=row.job_id, kind_id=BILL_OF_LADING_SIGNED,
                         actor=row.signer_name or '', by_rep=False, spot=row.spot + 1, created_at=row.signed_at))
    if rows:
        connection.execute(CustomerActivity.__table__.insert(), rows)
    return len(rows)
