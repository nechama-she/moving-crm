"""Keep saved job data independent of quote generation."""
import json
import logging

from fastapi import HTTPException


def attempt_pricing(lead, job, db, calculate, require_price=False):
    try:
        with db.begin_nested():
            result = calculate()
            if require_price and result is None:
                raise HTTPException(422, 'No matching rate is configured for this route.')
            if require_price:
                selection = json.loads(job.customer_packing_package or '{}')
                selection.pop('pricing_pending', None)
                selection.pop('pricing_save_error', None)
                job.customer_packing_package = json.dumps(selection)
        return ''
    except Exception as exc:
        logging.getLogger(__name__).exception('Pricing failed after saving job details: %s', job.id)
        reason = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else 'Pricing could not be calculated.'
        message = 'Changes saved. Estimate pending: ' + reason
        from models import LeadJobCharge, PublicMoveAccess
        from routes.leads import _refresh_lead_estimated_total
        selection = json.loads(job.customer_packing_package or '{}')
        selection.update(pricing_pending=True, pricing_save_error=message)
        job.customer_packing_package = json.dumps(selection)
        job.price = None
        db.query(LeadJobCharge).filter_by(job_id=job.id).delete()
        for access in db.query(PublicMoveAccess).filter_by(job_id=job.id).all():
            access.published_price = None
        _refresh_lead_estimated_total(lead.id, db)
        return message
