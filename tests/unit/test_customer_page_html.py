import ast
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import hmac

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
sys.path.insert(0, str(BACKEND))
from customer_page_html import render


class InitialHtmlTests(unittest.TestCase):
    def test_initial_html_contains_move_without_javascript(self):
        result = render('<div id="root"></div>', {'move': {'name': 'Jane', 'pickup': 'Maryland', 'delivery': 'Florida'}})
        self.assertIn('<dd>Maryland</dd>', result)
        self.assertIn('<dd>Florida</dd>', result)
        self.assertIn('move-bootstrap', result)

    def test_html_and_embedded_json_escape_customer_text(self):
        attack = '</script><script>alert(1)</script>'
        result = render('<div id="root"></div>', {'move': {'name': attack}})
        self.assertNotIn(attack, result)
        payload = result.split('type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)['move']['name'], attack)

    def test_unverified_response_has_no_customer_data(self):
        self.assertEqual(render('<div id="root"></div>'), '<div id="root"></div>')


class InitialHtmlAuthTests(unittest.TestCase):
    def setUp(self):
        now = datetime.utcnow()
        self.access = SimpleNamespace(id='move', revoked=False, expires_at=now+timedelta(hours=8))
        self.session = SimpleNamespace(access_id='move', expires_at=now+timedelta(hours=1), contact_hash='fingerprint')
        self.request = SimpleNamespace(query_params={}, cookies={'cm_customer': 'session-token'}, scope={})
        self.move = Mock(return_value={'name':'Private Name'})
        self.renderer = Mock(return_value='rendered')
        tree = ast.parse((BACKEND/'routes/public_moves.py').read_text(encoding='utf-8'))
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'initial_move_page')
        func.decorator_list = []
        func.args.defaults = []
        self.scope = {'__file__': str(BACKEND/'routes/public_moves.py'), 'PublicMoveAccess': 'access', 'PublicMoveSession': 'session',
                      'digest': lambda token: token, 'NOW': lambda: now, 'rep_link_token': lambda a: 'rep-key',
                      'link_token': lambda a: 'customer-key', 'Request': lambda scope: scope,
                      'verification_fingerprint': lambda *a: 'fingerprint', 'hmac':hmac, 'timezone':timezone,
                      'move_section': self.move}
        exec(compile(ast.Module(body=[ast.parse('from __future__ import annotations').body[0], func], type_ignores=[]), 'html-route', 'exec'), self.scope)

    def run_route(self):
        db = SimpleNamespace(get=lambda model, id: self.access if model == 'access' else self.session)
        modules = {'fastapi.responses': SimpleNamespace(HTMLResponse=lambda body, headers: SimpleNamespace(body=body, headers=headers)),
                   'customer_page_html': SimpleNamespace(render=self.renderer)}
        with patch.dict(sys.modules, modules), patch.object(Path, 'read_text', return_value='<div id="root"></div>'):
            return self.scope['initial_move_page']('move', self.request, db)

    def test_verified_move_is_included_and_not_cacheable(self):
        response = self.run_route()
        bootstrap = self.renderer.call_args.args[1]
        self.assertEqual(bootstrap['move']['name'], 'Private Name')
        self.assertEqual(bootstrap['session'], 'session-token')
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')

    def test_revoked_expired_wrong_move_and_contact_never_include_details(self):
        for attribute, value, target in [('revoked',True,'access'), ('expires_at', datetime.utcnow()-timedelta(seconds=1),'session'), ('access_id','another-move','session'), ('contact_hash','changed','session')]:
            with self.subTest(attribute=attribute):
                obj = getattr(self, target)
                old = getattr(obj, attribute)
                setattr(obj, attribute, value)
                self.run_route()
                self.assertIsNone(self.renderer.call_args.args[1])
                self.move.assert_not_called()
                setattr(obj, attribute, old)

    def test_customer_cookie_is_not_used_for_rep_page(self):
        self.request.query_params = {'audience':'rep'}
        self.run_route()
        self.assertIsNone(self.renderer.call_args.args[1])
        self.move.assert_not_called()


if __name__ == '__main__':
    unittest.main()
