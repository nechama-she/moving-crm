import ast
import re
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as Row
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
from charge_errors import isolated_charge, pending_line, PREFIX
from models import LeadJobCharge


def test_failed_charge_does_not_save_partial_rows_and_retry_clears_error():
    db = MagicMock()
    db.get.return_value = None
    job = Row(id='job')
    @isolated_charge('Storage')
    def calculate(job, db, fail):
        db.add(LeadJobCharge(id='storage', job_id=job.id, name='Storage', total_cost=30))
        if fail:
            raise ValueError('Missing storage rate')
        return Decimal(30)
    assert calculate(job, db, True) == 0
    saved = db.add.call_args.args[0]
    assert saved.name == 'Storage' and saved.total_cost == 0
    assert saved.description.startswith(PREFIX)
    assert db.add.call_count == 1
    db.get.return_value = saved
    assert calculate(job, db, False) == 30
    assert db.add.call_args.args[0].id == 'storage'
    db.delete.assert_called_once_with(saved)


@pytest.mark.parametrize('error', [HTTPException(403, 'Forbidden'), OperationalError('sql', {}, Exception('offline'))])
def test_access_and_database_errors_are_not_pricing_errors(error):
    @isolated_charge('Storage')
    def calculate(job, db):
        raise error
    with pytest.raises(type(error)):
        calculate(Row(id='job'), MagicMock())


def load_calculator():
    source = BACKEND / 'routes/pricing.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'compute_plan_calculation')
    for arg in node.args.args:
        arg.annotation = None
    scope = dict(Decimal=Decimal, re=re, pending_line=pending_line,
        _rounded_cubic_feet=lambda value: value,
        _transportation_price=lambda *args: (None, Decimal(100), None, Decimal(100)),
        _service_billable_volume=lambda *args: 100,
        _seasonal_charge=lambda *args: None, _parsed_move_date=lambda value: value,
        _packing_service_charges=lambda *args: [], _bulky_item_charges=lambda *args: [],
        _rule_charges=lambda rule: [rule.charge],
        _charge_amount=lambda charge, *args: Decimal(charge['rate']),
        elevator_card=lambda *args: None, elevator_quote=lambda *args: None,
        long_carry_card=lambda *args: None, long_carry_quote=lambda *args: None,
        stairs_card=lambda *args: None, stairs_quote=lambda *args: None,
        storage_card=lambda *args: None, storage_quote=lambda *args: None)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope


def test_bad_charge_does_not_block_transport_or_other_charges():
    scope = load_calculator()
    def charge(name, rate):
        return dict(id=name, name=name, description='', rate=rate, calculation_type='fixed', default_selected=True, automatic=False, applies=True)
    plan = Row(fuel_percent=None, services=[], rules=[Row(id='bad', charge=charge('Storage', 'invalid')), Row(id='good', charge=charge('Handling', '25'))])
    body = Row(cubic_feet=100, destination='MD', move_date='', quantities={}, bulky_items=[], selected_charges={}, manual_amounts={}, available_date='', delivery_address='')
    result = scope['compute_plan_calculation'](plan, body)
    assert result['total'] == 125
    assert result['incomplete']
    assert next(c for c in result['charges'] if c['name']=='Storage')['pending']
    assert next(c for c in result['charges'] if c['name']=='Handling')['amount'] == 25


def test_access_service_failure_keeps_other_services():
    scope = load_calculator()
    def fail(*args):
        raise ValueError('Missing elevator rate')
    scope['elevator_quote'] = fail
    scope['storage_quote'] = lambda *args: dict(valid=True, total=40, description='Storage')
    plan = Row(fuel_percent=None, services=[], rules=[])
    body = Row(cubic_feet=100, destination='MD', move_date='', quantities={}, bulky_items=[], selected_charges={}, manual_amounts={}, available_date='', delivery_address='')
    result = scope['compute_plan_calculation'](plan, body)
    assert result['total'] == 140
    assert any(c['name']=='Elevator' and c.get('pending') for c in result['charges'])


def test_bad_packing_item_keeps_other_packing_items():
    source = BACKEND / 'routes/pricing.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'customer_package_lines')
    scope = {'Decimal': Decimal, 'pending_line': pending_line}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    package = {'rates': {}, 'items': [], 'box_items': [
        {'id': 'bad', 'label': 'Dish Pack', 'quantity': 2, 'available': False},
        {'id': 'good', 'label': 'Small Box', 'quantity': 3, 'available': True, 'labor_price': 10, 'material_price': 6},
    ]}
    lines = scope['customer_package_lines'](package, {'mode': 'none', 'box_quantities': {'bad': 2, 'good': 3}})
    assert len(lines) == 2 and lines[0]['pending']
    assert lines[1]['amount'] == 48


def test_local_travel_failure_keeps_moving_and_fuel():
    from local_pricing import LocalCalculation, LocalSettings, calculate_local
    source = BACKEND / 'routes/local_pricing.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'calculate_book_price')
    def no_route(*args):
        raise HTTPException(422, 'Driving miles unavailable')
    scope = dict(load_settings=lambda *args: LocalSettings(), book_travel=no_route,
                 LocalCalculation=LocalCalculation, calculate_local=calculate_local, HTTPException=HTTPException)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    quote = scope['calculate_book_price'](None, LocalCalculation(cubic_feet=100), None, 'pickup', 'delivery')
    assert quote['total'] == 549
    assert quote['incomplete']
    assert quote['charges'][-1]['name'] == 'Travel fee'
    assert quote['charges'][-1]['pending']


def test_failed_transport_marks_dependent_fuel_pending_but_keeps_flat_charge():
    scope = load_calculator()
    def fail(*args):
        raise ValueError('Transportation rate missing')
    scope['_transportation_price'] = fail
    charge = dict(id='handling', name='Handling', description='', rate=25, calculation_type='fixed', default_selected=True, automatic=False, applies=True)
    plan = Row(fuel_percent=10, services=[], rules=[Row(id='handling', charge=charge)])
    body = Row(cubic_feet=100, destination='MD', move_date='', quantities={}, bulky_items=[], selected_charges={}, manual_amounts={}, available_date='', delivery_address='')
    result = scope['compute_plan_calculation'](plan, body)
    assert result['total'] == 25
    assert {line['name'] for line in result['charges'] if line.get('pending')} == {'Transportation charge', 'Fuel surcharge'}
