"""Refresh expired estimates without rerunning inventory or changing booked prices."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from models import LeadJobCharge, PublicMoveAccess


def price_is_locked(lead, job):
    return bool(lead.booked_move_date or job.booked_move_date or
                (lead.status or '').lower() in {'booked', 'confirmed', 'scheduled', 'completed', 'lost', 'cancelled'})


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value


def refresh_expired_price(lead, job, db, now=None):
    now = now or datetime.utcnow()
    if job.price is None or (job.price <= 0 and not job.price_calculated_at) or price_is_locked(lead, job):
        return False
    # Serialize concurrent page opens and recheck the saved calculation time.
    db.refresh(lead, with_for_update=True)
    db.refresh(job, with_for_update=True)
    if job.price is None or (job.price <= 0 and not job.price_calculated_at) or price_is_locked(lead, job):
        return False
    calculated = job.price_calculated_at
    if calculated is None:
        calculated = db.query(func.max(LeadJobCharge.updated_at)).filter_by(job_id=job.id).scalar()
        calculated = calculated or db.query(func.max(PublicMoveAccess.published_at)).filter_by(job_id=job.id).scalar()
        calculated = calculated or job.created_at
    # All books have at least one day of validity; fresh quotes need no pricing lookup.
    if not calculated or now < utc_naive(calculated) + timedelta(days=1):
        return False
    if job.price_refresh_attempted_at and now < utc_naive(job.price_refresh_attempted_at) + timedelta(minutes=5):
        return False
    try:
        with db.begin_nested():
            from routes.pricing import infer_job_move_type, calculate_and_save_lead_job_price
            _, plan = infer_job_move_type(lead, job, db)
            if not plan:
                raise HTTPException(422, 'No pricing book matches this move.')
            if now < utc_naive(calculated) + timedelta(days=plan.price_valid_days or 7):
                return False
            price = calculate_and_save_lead_job_price(lead, job, db)
            if price is None:
                raise HTTPException(422, 'No matching price is configured for this move.')
            job.price_calculated_at = now
            job.price_refresh_error = None
            for access in db.query(PublicMoveAccess).filter_by(job_id=job.id).all():
                access.published_price = price
                access.published_cuft = lead.volume
                access.published_at = now
    except Exception:
        # The savepoint restores charges, answers, and published totals on failure.
        job.price_refresh_error = 'Could not refresh the expired price. Your previous estimate is unchanged. Please retry Calculate price.'
    job.price_refresh_attempted_at = now
    db.commit()
    return not bool(job.price_refresh_error)
