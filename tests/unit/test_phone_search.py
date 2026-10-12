import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, literal, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from phone_search import phone_search_condition


@pytest.mark.parametrize("stored,search,expected", [
    ("3862141865", "+13862141865", True),
    ("+13862141865", "3862141865", True),
    ("(386) 214-1865", "+1 (386) 214-1865", True),
    ("3862141866", "+13862141865", False),
    (None, "+13862141865", False),
    ("3862141865", "customer 3862141865", False),
    ("3862141865", "", False),
    ("3862141865", "+443862141865", False),
])
def test_phone_search(stored, search, expected):
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.connection.create_function("regexp_replace", 4,
            lambda value, pattern, replacement, flags: re.sub(pattern, replacement, value) if value is not None else None)
        result = connection.scalar(select(phone_search_condition(literal(stored), search)))
        assert bool(result) is expected
    engine.dispose()
