"""Verify calculator prices replace the job total and breakdown together."""
import ast
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


@pytest.fixture
def pricing():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    names = {'LeadJobChargePayload', 'LeadJobChargesBody', 'SaveJobPriceBody', '_to_money_decimal', 'save_lead_job_price'}
    nodes = [node for node in ast.parse(source.read_text()).body if getattr(node, 'name', '') in names]
    scope = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, Decimal=Decimal,
                 InvalidOperation=InvalidOperation, HTTPException=HTTPException,
                 ExternalLeadUpdateLog=dict)
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
            node.args.defaults = []
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
    row = SimpleNamespace(id='job-2', price=Decimal('123'))
    scope.update(_ensure_not_dispatch_write=MagicMock(), _get_job_or_404=MagicMock(return_value=row),
                 Lead=SimpleNamespace(id='id'), _refresh_lead_estimated_total=MagicMock(),
                 _replace_job_charges=MagicMock(), _serialize_job_with_addresses=lambda job, db: {'price': job.price})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    return scope, row, MagicMock()


def test_saves_total_and_only_nonzero_lines(pricing):
    api, row, db = pricing
    body = api['SaveJobPriceBody'](price='9353.00', estimatedCharges=[
        {'name': 'Transportation', 'subtotal': 8100, 'totalCost': 8100},
        {'name': 'Fuel', 'subtotal': 1053, 'totalCost': 1053},
        {'name': 'Piano', 'subtotal': 0, 'totalCost': 0},
        {'name': 'Destination and origin', 'subtotal': 250, 'discountAmount': 50, 'totalCost': 200},
    ])
    user = object()
    api['save_lead_job_price']('lead-1', 'job-2', body, user, db)
    api['_get_job_or_404'].assert_called_once_with('lead-1', 'job-2', user, db)
    saved = api['_replace_job_charges'].call_args.args[1]
    assert [charge.name for charge in saved] == ['Transportation', 'Fuel', 'Destination and origin']
    assert saved[-1].discount_amount == 50
    assert row.price == Decimal('9353.00')
    api['_refresh_lead_estimated_total'].assert_called_once_with('lead-1', db)
    db.commit.assert_called_once()


@pytest.mark.parametrize('price', ['0', '-1', 'NaN', 'Infinity'])
def test_invalid_total_cannot_overwrite_existing_price(pricing, price):
    api, row, db = pricing
    with pytest.raises(ValueError):
        api['SaveJobPriceBody'](price=price)
    assert row.price == Decimal('123')
    db.commit.assert_not_called()


def test_mismatched_total_does_not_mutate_job(pricing):
    api, row, db = pricing
    body = api['SaveJobPriceBody'](price=100, estimatedCharges=[{'name': 'Transport', 'subtotal': 50, 'totalCost': 50}])
    with pytest.raises(HTTPException):
        api['save_lead_job_price']('lead-1', 'job-2', body, object(), db)
    api['_replace_job_charges'].assert_not_called()
    assert row.price == Decimal('123')
    db.commit.assert_not_called()


def test_inaccessible_job_cannot_be_priced(pricing):
    api, row, db = pricing
    api['_get_job_or_404'].side_effect = HTTPException(404, 'Job not found')
    with pytest.raises(HTTPException):
        api['save_lead_job_price']('other', 'job-2', api['SaveJobPriceBody'](price=100), object(), db)
    api['_replace_job_charges'].assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize('existing_tax', [0, 25])
def test_lead_summary_includes_all_jobs_and_discounts(existing_tax):
    import json
    source = Path(__file__).resolve().parents[2] / 'backend/routes/leads.py'
    names = {'EstimatedTotalPayload', '_serialize_estimated_total', '_deserialize_estimated_total', '_to_money_decimal', '_refresh_lead_estimated_total'}
    nodes = [node for node in ast.parse(source.read_text()).body if getattr(node, 'name', '') in names]
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
    lead = SimpleNamespace(estimated_total=json.dumps({'tax': existing_tax, 'taxableAmount': 250}) if existing_tax else None)
    jobs = [SimpleNamespace(price=Decimal('1500'), charges=[SimpleNamespace(total_cost=Decimal('1500'), discount_amount=Decimal('100'))]),
            SimpleNamespace(price=Decimal('200'), charges=[]),
            SimpleNamespace(price=None, charges=[SimpleNamespace(total_cost=Decimal('82'), discount_amount=Decimal('0'))])]
    db = MagicMock(); db.get.return_value = lead
    db.query.return_value.filter.return_value.all.return_value = jobs
    scope = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, Decimal=Decimal, InvalidOperation=InvalidOperation,
                 HTTPException=HTTPException, json=json, Lead=object(), LeadJob=SimpleNamespace(lead_id='lead_id'))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    scope['_refresh_lead_estimated_total']('lead-1', db)
    total = json.loads(lead.estimated_total)
    assert total['subtotal'] == 1882
    assert total['finalTotal'] == 1782 + existing_tax
    assert total['tax'] == existing_tax
    assert total['taxableAmount'] == (250 if existing_tax else 0)
    db.flush.assert_called_once()
    assert db.expire.call_count == 3
