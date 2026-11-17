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
        final += Decimal(str(row.price)) if row.price is not None else sum((Decimal(str(c.total_cost or 0)) for c in charges), Decimal(0))
        discounts += sum((Decimal(str(c.discount_amount or 0)) for c in charges), Decimal(0))
    # Written straight to the table: SmartMoving's prices are not on the estimate, so a rep's approval stays.
    from sqlalchemy import update
    db.execute(update(Lead).where(Lead.id == job.lead_id).values(estimated_total=json.dumps(
        {'subtotal': float(final + discounts), 'taxableAmount': 0.0, 'tax': 0.0, 'finalTotal': float(final)}))
        .execution_options(synchronize_session=False))
    lead = db.identity_map.get(db.identity_key(Lead, job.lead_id))
    if lead is not None:
        db.expire(lead, ['estimated_total'])


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
