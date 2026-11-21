"""Which price a job has: ours (the CRM's lines) or SmartMoving's. The one rule every price and total follows.

- Signed on our customer page: ours (SmartMoving's lines were deleted at signing).
- Booked and not signed with us: SmartMoving's (ours only when SmartMoving has none).
- Otherwise: ours when we priced it, else SmartMoving's.

The other price's lines stay saved; they are not shown or counted."""
from price_validity import is_booked


def is_ours(charge):
    """A line of ours: the calculator's, the customer's answers', a section discount (anything not SmartMoving's)."""
    return (charge.source or '') != 'smartmoving'


def job_price_source(lead, job, signed):
    """'crm' or 'smartmoving' for this job; signed: whether the job has a signed estimate with us."""
    if signed:
        return 'crm'
    if is_booked(lead.status):
        return 'smartmoving' if any(not is_ours(charge) for charge in job.charges) else 'crm'
    return 'crm' if any(is_ours(charge) for charge in job.charges) else 'smartmoving'


def counted_charges(lead, job, signed):
    """The job's lines of its price (job_price_source)."""
    ours = job_price_source(lead, job, signed) == 'crm'
    return [charge for charge in job.charges if is_ours(charge) == ours]


def signed_job_ids(db, job_ids):
    """Which of these jobs have a signed estimate with us, in one query."""
    from models import EstimateSignature
    if not job_ids:
        return set()
    return {row[0] for row in db.query(EstimateSignature.job_id).filter(
        EstimateSignature.job_id.in_(list(job_ids)), EstimateSignature.signed_at.isnot(None)).distinct()}
