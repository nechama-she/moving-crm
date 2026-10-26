import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from rep_discounts import apply


class RepDiscountTests(unittest.TestCase):
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
