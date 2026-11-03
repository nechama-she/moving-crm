import ast
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[2] / 'backend/routes/public_moves.py'


def cards_function(builds):
    """_customer_pricing_options on its own, with the route and builder it uses stood in."""
    module = ast.parse(SOURCE.read_text(encoding='utf-8'))
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == '_customer_pricing_options')
    node.decorator_list = []
    scope = {'json': json, 'LeadLiveSwitch': object(),
             '_read_job_route': lambda db, job: (job.pickup_zip, [], job.delivery_zip),
             '_build_customer_pricing_options': lambda lead, job, db: builds.append(1) or {'stairs': {'rate': Decimal('0.20')}, 'minimum_cuft': 286}}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope['_customer_pricing_options']


def test_cards_are_read_as_saved_and_built_again_only_when_an_input_changes(monkeypatch):
    monkeypatch.setitem(sys.modules, 'routes.pricing', SimpleNamespace(infer_job_move_type=lambda lead, job, db: ('Long Distance', None)))
    builds = []
    cards = cards_function(builds)
    conversation = SimpleNamespace(details='{"spark_inventory_snapshot": []}')
    db = SimpleNamespace(get=lambda model, key: conversation)
    lead = SimpleNamespace(id='lead', volume=Decimal('1253'))
    job = SimpleNamespace(pricing_match_key='match', customer_packing_package='{}', customer_packing='{}',
                          estimated_materials='[]', move_date='2026-09-29', stop_types='[]', pickup_zip='20850',
                          delivery_zip='30301', pricing_options_cache=None, pricing_options_key=None)

    first = cards(lead, job, db)
    assert first == {'stairs': {'rate': 0.2}, 'minimum_cuft': 286}
    assert cards(lead, job, db) == first
    assert len(builds) == 1

    for change in ({'customer_packing_package': '{"stairs": {"pickup": 3}}'}, {'delivery_zip': '10001'}, {'pricing_match_key': 'other'}):
        for name, value in change.items():
            setattr(job, name, value)
        cards(lead, job, db)
    conversation.details = '{"spark_inventory_snapshot": [{"name": "Chair"}]}'
    cards(lead, job, db)
    assert len(builds) == 5
