"""Dispatch selection validation without loading external service integrations."""
import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


@pytest.fixture
def validate():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if getattr(n, 'name', '') == '_validate_dispatch_company')
    scope = {'Session': object, 'Company': object, 'HTTPException': HTTPException}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['_validate_dispatch_company']


@pytest.mark.parametrize('value', [None, '', '  '])
def test_clear_uses_contract_company(validate, value):
    db = MagicMock()
    assert validate(value, [], db) is None
    db.get.assert_not_called()


def test_assign_accessible_company(validate):
    assert validate(' rapid ', ['rapid'], MagicMock()) == 'rapid'


def test_reject_inaccessible_company(validate):
    db = MagicMock()
    with pytest.raises(HTTPException) as error:
        validate('rapid', ['gorilla'], db)
    assert error.value.status_code == 403
    db.get.assert_not_called()


def test_reject_missing_company(validate):
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(HTTPException) as error:
        validate('rapid', ['rapid'], db)
    assert error.value.status_code == 404
