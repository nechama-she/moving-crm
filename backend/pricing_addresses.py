"""Pricing locations: the state and ZIP the browser saved for an address, or read from the address itself."""
from functools import wraps
from contextvars import ContextVar
import json

from fastapi import HTTPException

from zip_state import delivery_location

_locations = ContextVar('pricing_locations', default=())


def saved_location(address):
    return next((row for row in _locations.get() if row['address'].strip().lower() == (address or '').strip().lower()), None)


def with_job_locations(function):
    @wraps(function)
    def wrapped(lead, job, db, *args, **kwargs):
        selection = json.loads(getattr(job, 'customer_packing_package', None) or '{}')
        token = _locations.set(selection.get('pricing_locations', []))
        try:
            return function(lead, job, db, *args, **kwargs)
        finally:
            _locations.reset(token)
    return wrapped


def pricing_location(value: str | None) -> tuple[str, str]:
    address = (value or '').strip()
    if not address:
        return '', ''
    saved = saved_location(address)
    if saved:
        return saved['state'], saved['zip_code']
    state, zip_code = delivery_location(address)
    if state:
        return state, zip_code
    raise HTTPException(422, 'Could not find the state for this address. Select the address from the suggestions.')


@with_job_locations
def job_location(lead, job, db, address):
    return pricing_location(address)
