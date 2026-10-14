import ast
import re
from decimal import Decimal
from pathlib import Path


def test_box_packing_groups_across_rooms_without_changing_totals():
    source = Path(__file__).resolve().parents[2] / 'backend/routes/public_moves.py'
    module = ast.parse(source.read_text(encoding='utf-8'))
    helper = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == '_group_box_packing_charges')
    scope = {'re': re, 'Decimal': Decimal}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), 'exec'), scope)
    def line(name, quantity, total, description=None):
        return dict(name=name, description=description or f'Movers pack {quantity} of {quantity} boxes; labor and materials included', total=total, subtotal=total, discount_amount=0, discount_percent=0)
    charges = [line('Small Box Packing', 1, 16), line('Medium Box Packing', 1, 20), line('Small Box Packing', 2, 32), line('Medium Box Packing', 2, 40), line('Transportation', 1, 100, 'Base move')]
    result = scope['_group_box_packing_charges'](charges)
    assert len(result) == 3
    assert result[0]['total'] == 48
    assert result[0]['description'] == 'Movers pack 3 of 3 boxes; labor and materials included'
    assert result[1]['total'] == 60
    assert sum(row['total'] for row in result) == sum(row['total'] for row in charges)
    assert charges[0]['total'] == 16
    assert result[2] == charges[4]
