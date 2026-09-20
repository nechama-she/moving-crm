import ast
import math
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def pricing():
    source = Path(__file__).resolve().parents[2] / "backend/routes/pricing.py"
    names = {"_transportation_price", "_rounded_cubic_feet", "compute_plan_calculation", "lookup_pricing"}
    nodes = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
        node.args.defaults = []
        node.returns = None
        for arg in node.args.args:
            arg.annotation = None
    scope = {"Decimal": Decimal, "math": math, "re": re,
             "_seasonal_charge": lambda *args: None, "_parsed_move_date": lambda *args: None,
             "_packing_service_charges": lambda *args: [], "_bulky_item_charges": lambda *args: []}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    return scope


def rate(low, high, price="4.25", minimum="1692.80"):
    row = SimpleNamespace(destination="NY", cubic_feet_min=low, cubic_feet_max=high,
                          rate=Decimal(price), minimum_price=Decimal(minimum) if minimum else None)
    row.to_dict = lambda: {"destination": row.destination, "min": low}
    return row


@pytest.mark.parametrize("volume,expected", [(5, 1692.80), (181.1, 1692.80), (280, 1692.80),
    (285, 1692.80), (286, 1692.80), (500, 2125), (800, 3400), (801, 3204)])
def test_calculator_and_quote_share_minimum_rule(pricing, volume, expected):
    plan = SimpleNamespace(rates=[rate(801, None, "4"), rate(286, 800)],
                           fuel_percent=Decimal(13), services=[], rules=[])
    body = SimpleNamespace(destination=" ny ", cubic_feet=volume, move_date=None,
                           quantities={}, bulky_items=[], selected_charges={}, manual_amounts={})
    result = pricing["compute_plan_calculation"](plan, body)
    pricing["_plan_or_404"] = lambda *args: plan
    quote = pricing["lookup_pricing"]("plan", "NY", volume, None, None)
    assert result["base_price"] == quote["base_price"] == expected
    assert result["total"] == pytest.approx(expected * 1.13)
    assert quote["total_before_services"] == pytest.approx(expected * 1.13)
    assert body.cubic_feet == volume


@pytest.mark.parametrize("destination,volume", [("NJ", 5), ("NY", 850), ("NY", 1100)])
def test_no_fallback_for_other_destinations_or_gaps(pricing, destination, volume):
    plan = SimpleNamespace(rates=[rate(286, 800), rate(900, 1000)])
    assert pricing["_transportation_price"](plan, destination, volume)[3] is None


def test_below_band_requires_configured_minimum(pricing):
    plan = SimpleNamespace(rates=[rate(286, 800, minimum=None)])
    assert pricing["_transportation_price"](plan, "NY", 5)[3] is None
