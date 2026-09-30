"""Isolate charge calculation failures; never hide persistence or access failures."""
import inspect
import logging
from decimal import Decimal
from functools import wraps
from uuid import NAMESPACE_URL, uuid5
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

PREFIX = 'Calculation pending: '


def error_description(error):
    if isinstance(error, SQLAlchemyError):
        raise error
    if isinstance(error, HTTPException) and error.status_code in (401, 403, 404):
        raise error
    logging.getLogger(__name__).warning('Charge calculation failed', exc_info=error)
    detail = error.detail if isinstance(error, HTTPException) else str(error) if isinstance(error, (ValueError, ArithmeticError)) else 'Unable to calculate this charge. Please retry.'
    return PREFIX + (detail if isinstance(detail, str) else 'Unable to calculate this charge. Please retry.') + ' Not included in the total yet.'


def pending_line(key, name, error):
    return {'id': key, 'name': name, 'description': error_description(error), 'pending': True,
            'calculation_type': 'fixed', 'rate': 0, 'amount': Decimal(0), 'selected': True,
            'default_selected': True, 'automatic': True, 'applies': True, 'required': True,
            'quantity_label': '', 'subtotal': Decimal(0), 'discountAmount': Decimal(0), 'totalCost': Decimal(0)}


class ChargeBuffer:
    def __init__(self, db):
        self.db, self.rows = db, []

    def __getattr__(self, key):
        return getattr(self.db, key)

    def add(self, row):
        from models import LeadJobCharge
        if isinstance(row, LeadJobCharge):
            self.rows.append(row)
        else:
            self.db.add(row)


def isolated_charge(name):
    """Stage charge rows so a failed calculation cannot leave partial charges."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            from models import LeadJobCharge
            bound = signature.bind(*args, **kwargs)
            db, job = bound.arguments['db'], bound.arguments['job']
            buffer = ChargeBuffer(db)
            bound.arguments['db'] = buffer
            try:
                amount = function(*bound.args, **bound.kwargs)
            except Exception as error:
                description = error_description(error)
                key = str(uuid5(NAMESPACE_URL, f'pending-charge:{job.id}:{function.__name__}'))
                db.add(LeadJobCharge(id=key, job_id=job.id, name=name, description=description,
                                    subtotal=0, discount_amount=0, total_cost=0, sort_order=2999))
                return Decimal(0)
            for row in buffer.rows:
                db.add(row)
            # Remove an earlier error after a successful retry, including partial syncs.
            key = str(uuid5(NAMESPACE_URL, f'pending-charge:{job.id}:{function.__name__}'))
            old = db.get(LeadJobCharge, key)
            if old is not None:
                db.delete(old)
            return amount
        return wrapped
    return decorate
