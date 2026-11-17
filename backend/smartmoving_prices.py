"""A job signed on the customer page has no SmartMoving prices: they are deleted, and the lead's total is the total of
its jobs, without SmartMoving's tax. The SmartMoving sync stops at the signature, so they never come back."""
import json
from decimal import Decimal


def drop_smartmoving_prices(db, job):
    """Deletes the job's SmartMoving price lines and price, and sets the lead's total from its jobs. Does not commit."""
    from models import Lead, LeadJob, LeadJobCharge
    db.query(LeadJobCharge).filter(LeadJobCharge.job_id == job.id, LeadJobCharge.source == 'smartmoving').delete(synchronize_session=False)
    job.smartmoving_price = None
    db.flush()
    final, discounts = Decimal(0), Decimal(0)
    for row in db.query(LeadJob).filter(LeadJob.lead_id == job.lead_id).all():
        charges = db.query(LeadJobCharge).filter(LeadJobCharge.job_id == row.id).all()
        # The job's lines, as its Charges box adds them; the saved price only for a job without lines.
        final += sum((Decimal(str(c.total_cost or 0)) for c in charges), Decimal(0)) if charges or row.price is None else Decimal(str(row.price))
        discounts += sum((Decimal(str(c.discount_amount or 0)) for c in charges), Decimal(0))
    # Written straight to the table: SmartMoving's prices are not on the estimate, so a rep's approval stays.
    from sqlalchemy import update
    db.execute(update(Lead).where(Lead.id == job.lead_id).values(estimated_total=json.dumps(
        {'subtotal': float(final + discounts), 'taxableAmount': 0.0, 'tax': 0.0, 'finalTotal': float(final)}))
        .execution_options(synchronize_session=False))
    lead = db.identity_map.get(db.identity_key(Lead, job.lead_id))
    if lead is not None:
        db.expire(lead, ['estimated_total'])


def detach_from_smartmoving(db, lead):
    """The lead leaves SmartMoving: its SmartMoving id is moved to detached_smartmoving_leads. Does not commit."""
    from models import DetachedSmartMovingLead
    smartmoving_id = (lead.smartmoving_id or '').strip()
    if smartmoving_id:
        db.merge(DetachedSmartMovingLead(smartmoving_id=smartmoving_id, lead_id=lead.id))
    lead.smartmoving_id = None


def detach_signed_leads(connection):
    """Once: the table, and every lead already signed on the customer page detached from SmartMoving. Returns how many."""
    from sqlalchemy import inspect
    from sqlalchemy.orm import Session
    from models import DetachedSmartMovingLead, EstimateSignature, Lead
    if not inspect(connection).has_table(DetachedSmartMovingLead.__tablename__):
        DetachedSmartMovingLead.__table__.create(connection)
    with Session(bind=connection) as db:
        signed = db.query(EstimateSignature.lead_id).filter(EstimateSignature.signed_at.isnot(None))
        leads = db.query(Lead).filter(Lead.id.in_(signed), Lead.smartmoving_id.isnot(None), Lead.smartmoving_id != '').all()
        for lead in leads:
            detach_from_smartmoving(db, lead)
        db.flush()
    return len(leads)


def drop_signed_smartmoving_prices(connection):
    """Once: every job already signed on the customer page. Returns how many."""
    from sqlalchemy.orm import Session
    from models import EstimateSignature, LeadJob
    with Session(bind=connection) as db:
        signed = db.query(EstimateSignature.job_id).filter(EstimateSignature.signed_at.isnot(None))
        jobs = db.query(LeadJob).filter(LeadJob.id.in_(signed)).all()
        for job in jobs:
            drop_smartmoving_prices(db, job)
        db.flush()
    return len(jobs)
