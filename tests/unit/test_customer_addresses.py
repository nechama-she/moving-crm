import sys
import time
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import customer_addresses as addresses


def test_signed_selection_is_checked(monkeypatch):
    secret = 'test-secret-with-at-least-thirty-two-characters'
    monkeypatch.setenv('JWT_SECRET', secret)
    address = {'place_id': 'place1', 'formatted_address': 'Miami, FL, USA', 'city': 'Miami', 'state': 'FL', 'country': 'US'}
    proof = jwt.encode({'sub': 'access1', 'aud': 'customer-address', 'exp': int(time.time()) + 3600, 'address': address}, secret, algorithm='HS256')
    shown = dict(address)
    selection = SimpleNamespace(proof=proof, model_dump=lambda **kw: dict(shown))
    addresses.validate_selection(selection, 'access1')
    with pytest.raises(HTTPException): addresses.validate_selection(selection, 'other-access')
    shown['city'] = 'Forged'
    with pytest.raises(HTTPException): addresses.validate_selection(selection, 'access1')
