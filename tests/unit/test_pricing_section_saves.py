"""Exercise the section handler without importing AWS or starting the app."""
import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))


class HttpError(Exception):
    def __init__(self, status, detail):
        self.status_code = status


class Row(SimpleNamespace):
    def model_dump(self, exclude=None):
        return {key: value for key, value in vars(self).items() if key not in (exclude or set())}


class SectionSaveTests(unittest.TestCase):
    def setUp(self):
        self.plan = Row(services=[], rates=[], rules=[Row(id='rule', description='keep')], pickup_regions='original', name='Original', fuel_percent=13)
        self.plan.to_dict = lambda: {}
        tree = ast.parse((BACKEND / 'routes/pricing.py').read_text(encoding='utf-8'))
        handler = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'update_pricing_section')
        handler.decorator_list = []
        handler.args.defaults = []
        future = ast.parse('from __future__ import annotations').body[0]
        self.scope = {'_plan_or_404': lambda *args: self.plan, 'HTTPException': HttpError, 'json': json,
                      'PricingService': Row, 'PricingRate': Row, 'PricingRule': Row}
        for key in ['EXTRA_STOPS', 'ELEVATOR', 'LONG_CARRY', 'STAIRS', 'STORAGE', 'ORIGIN_FEE', 'DELIVERY_FEE', 'SHUTTLE', 'PACKING_CARD']:
            self.scope[key + '_PREFIX'] = key + ':'
        self.scope['BULKY_ITEM_MARKER'] = 'BULKY:'
        exec(compile(ast.Module(body=[future, handler], type_ignores=[]), 'section-handler', 'exec'), self.scope)
        self.db = Mock()

    def save(self, section, **values):
        body = Row(**values, model_fields_set=set(values))
        with patch.dict(sys.modules, {'fastapi': SimpleNamespace(HTTPException=HttpError)}):
            self.scope['update_pricing_section']('plan', section, body, None, self.db)

    def test_each_fee_section_preserves_other_services_and_plan_fields(self):
        prefixes = {'extraStops': 'EXTRA_STOPS:', 'elevator': 'ELEVATOR:', 'longCarry': 'LONG_CARRY:',
                    'stairs': 'STAIRS:', 'storage': 'STORAGE:', 'originFees': 'ORIGIN_FEE:',
                    'deliveryFees': 'DELIVERY_FEE:', 'shuttle': 'SHUTTLE:', 'bulkyItems': 'BULKY:'}
        for section, prefix in prefixes.items():
            with self.subTest(section=section):
                changed = Row(id='target', name='Target', comments=prefix+'old', rate_text='10', sort_order=0)
                untouched = Row(id='other', name='Other', comments='other', rate_text='99', sort_order=1)
                self.plan.services = [changed, untouched]
                self.save(section, services=[Row(id='target', name='Target', comments=prefix+'new', rate_text='20')])
                self.assertEqual(changed.rate_text, '20')
                self.assertEqual(vars(untouched), dict(id='other', name='Other', comments='other', rate_text='99', sort_order=1))
                self.assertEqual(self.plan.pickup_regions, 'original')
                self.assertEqual(self.plan.fuel_percent, 13)
                self.assertEqual(self.plan.rules[0].description, 'keep')

    def test_details_save_preserves_all_rows(self):
        services, rules, rates = self.plan.services, self.plan.rules, self.plan.rates
        self.save('details', name='Updated', fuel_percent=10, price_valid_days=14)
        self.assertEqual((self.plan.name, self.plan.fuel_percent, self.plan.price_valid_days), ('Updated', 10, 14))
        self.assertIs(self.plan.services, services)
        self.assertIs(self.plan.rules, rules)
        self.assertIs(self.plan.rates, rates)
        self.assertEqual(self.plan.pickup_regions, 'original')

    def test_adjustments_save_preserves_discounts_and_other_cards(self):
        fee = Row(id='fee', name='Stairs', comments='STAIRS:config', rate_text='99', sort_order=0)
        service = Row(id='service', name='Extra', comments='', rate_text='10', sort_order=1)
        discount = Row(id='discount', category='discount_percent', title='Senior', description='10', sort_order=0)
        rule = Row(id='rule', category='general', title='Adjustment', description='old', sort_order=1)
        self.plan.services = [fee, service]
        self.plan.rules = [discount, rule]
        self.save('services', services=[Row(id='service', name='Extra', comments='', rate_text='20')], rules=[Row(id='rule', category='general', title='Adjustment', description='new')])
        self.assertEqual(service.rate_text, '20')
        self.assertEqual(rule.description, 'new')
        self.assertEqual(fee.rate_text, '99')
        self.assertEqual(discount.description, '10')
        self.assertEqual(self.plan.fuel_percent, 13)
        with self.assertRaises(HttpError):
            self.save('services', services=[], rules=[discount])

    def test_materials_and_packing_do_not_overwrite_each_other(self):
        for section, expected in [('materials', {'full':'2', 'materials':['new']}), ('packing', {'full':'8', 'materials':['old']})]:
            with self.subTest(section=section):
                row = Row(id='pack', name='Packing', rate_text='', comments='PACKING_CARD:'+json.dumps({'full':'2','materials':['old']}), sort_order=0)
                self.plan.services = [row]
                self.save(section, services=[Row(id='pack', name='Packing', rate_text='', comments='PACKING_CARD:'+json.dumps({'full':'8','materials':['new']}))])
                self.assertEqual(json.loads(row.comments.split(':', 1)[1]), expected)

    def test_rates_leave_services_unchanged(self):
        service = Row(id='service', comments='unchanged')
        self.plan.services = [service]
        self.plan.rates = [Row(id='rate', destination='NY', band_label='Standard', rate=7)]
        self.save('rates', rates=[Row(id='rate', destination='NY', band_label='Standard', rate=6)])
        self.assertEqual(self.plan.rates[0].rate, 6)
        self.assertIs(self.plan.services[0], service)
        self.assertEqual(self.plan.pickup_regions, 'original')

    def test_rejects_other_section_fields(self):
        with self.assertRaises(HttpError):
            self.save('stairs', services=[], rates=[])
        self.db.commit.assert_not_called()

    def test_rejects_service_from_other_section(self):
        with self.assertRaises(HttpError):
            self.save('stairs', services=[Row(id=None, name='Storage', comments='STORAGE:{}', rate_text='')])
        self.db.commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
