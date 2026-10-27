import json
import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from rep_discounts import apply


class RepDiscountTests(unittest.TestCase):
    def test_save_rate_discount_handler(self):
        source = Path(__file__).resolve().parents[2] / 'backend/routes/public_moves.py'
        handler = next(node for node in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(node, ast.FunctionDef) and node.name == 'save_rep_discount')
        handler.decorator_list = []
        handler.args.defaults = []
        scope = {'is_rep_request': lambda *args: True, 'Lead': object(), 'LeadJob': object(), 'json': json}
        future = ast.parse('from __future__ import annotations').body[0]
        exec(compile(ast.Module(body=[future, handler], type_ignores=[]), str(source), 'exec'), scope)
        lead = SimpleNamespace(id='lead', volume=Decimal('543'))
        job = SimpleNamespace(id='job', customer_packing_package='{}')
        charge = SimpleNamespace(id='charge', name='Transportation charge')
        db = Mock()
        db.get.return_value = lead
        db.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = job
        db.query.return_value.filter_by.return_value.first.return_value = charge
        refresh = Mock()
        with patch.dict(sys.modules, {'models': SimpleNamespace(LeadJobCharge=object()), 'price_validity': SimpleNamespace(price_is_locked=lambda *args: False), 'routes.leads': SimpleNamespace(_refresh_lead_estimated_total=refresh)}):
            result = scope['save_rep_discount'](SimpleNamespace(charge_id='charge', title='Discount', type='rate', value=Decimal('3.52'), remove=False), None, SimpleNamespace(lead_id='lead', job_id='job'), db)
        self.assertEqual(result, {'saved': True})
        saved = json.loads(job.customer_packing_package)['rep_discounts']['charge']
        self.assertEqual((saved['value'], saved['volume']), ('3.52', 543))
        refresh.assert_called_once_with('lead', db)
        db.commit.assert_called_once()

    def test_no_discounts_leaves_job_untouched_and_skips_rows(self):
        class UnusedRows:
            def __iter__(self):
                raise AssertionError('No discounts should not scan charges')
        job = SimpleNamespace(customer_packing_package='{"mode":"none"}')
        self.assertFalse(apply(job, UnusedRows()))
        self.assertEqual(job.customer_packing_package, '{"mode":"none"}')

    def setup_discount(self, kind='amount', value=100):
        job = SimpleNamespace(customer_packing_package=json.dumps({'rep_discounts': {'transport': {'title': 'Military', 'type': kind, 'value': value}}}))
        row = SimpleNamespace(id='transport', total_cost=Decimal('1000'), discount_amount=Decimal('0'), description='Transportation')
        return job, row

    def test_repeat_refresh_does_not_double_discount(self):
        job, row = self.setup_discount()
        apply(job, [row], 200)
        apply(job, [row], 200)
        self.assertEqual(row.total_cost, 900)
        self.assertEqual(row.discount_amount, 100)
        self.assertEqual(row.description, 'Transportation | Military: -$100.00')

    def test_new_total_is_a_discount_and_preserves_original(self):
        job, row = self.setup_discount('total', 700)
        apply(job, [row])
        apply(job, [row])
        self.assertEqual(row.total_cost, 700)
        self.assertEqual(row.discount_amount, 300)
        self.assertIn('Military: -$300.00', row.description)

    def test_higher_total_does_not_increase_price(self):
        job, row = self.setup_discount('total', 1500)
        apply(job, [row])
        self.assertEqual(row.total_cost, 1000)
        self.assertEqual(row.discount_amount, 0)

    def test_remove_restores_base(self):
        job, row = self.setup_discount()
        apply(job, [row])
        data = json.loads(job.customer_packing_package)
        data['rep_discounts'] = {}
        job.customer_packing_package = json.dumps(data)
        self.assertTrue(apply(job, [row]))
        self.assertEqual(row.total_cost, 1000)
        self.assertEqual(row.discount_amount, 0)

    def test_rate_uses_current_volume(self):
        job, row = self.setup_discount('rate', 3)
        apply(job, [row], 200)
        self.assertEqual(row.total_cost, 600)
        apply(job, [row], 250)
        self.assertEqual(row.total_cost, 750)

    def test_fee_waiver_and_cap(self):
        for kind, value in [('percent', 100), ('amount', 2000)]:
            job, row = self.setup_discount(kind, value)
            apply(job, [row])
            self.assertEqual(row.total_cost, 0)
            self.assertEqual(row.discount_amount, 1000)

    def test_existing_discount_preserved(self):
        job, row = self.setup_discount('percent', 50)
        row.discount_amount = Decimal('200')
        row.total_cost = Decimal('800')
        apply(job, [row])
        apply(job, [row])
        self.assertEqual(row.total_cost, 400)
        self.assertEqual(row.discount_amount, 600)


if __name__ == '__main__':
    unittest.main()
