import ast
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class ImportInventoryTests(unittest.TestCase):
    def test_import_only_adds_media_without_touching_active_report(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'backend/routes/liveswitch.py').read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'prepare_panel_upload', 'finish_panel_upload'}]
        for node in nodes:
            node.decorator_list = []
            node.args.defaults = []
        storage = Mock()
        storage.head_object.return_value = {'ContentLength': 10, 'ContentType': 'video/mp4'}
        context = Mock()
        archive = Mock(side_effect=AssertionError('Import must not archive inventory'))
        scope = dict(panel_upload_context=context, boto3=SimpleNamespace(client=lambda *args: storage),
                     LeadAttachment=lambda **values: SimpleNamespace(**values), archive_report_for_new_media=archive)
        future = ast.parse('from __future__ import annotations').body[0]
        exec(compile(ast.Module(body=[future, *nodes], type_ignores=[]), 'import-handlers', 'exec'), scope)
        lead, user = SimpleNamespace(id='lead'), SimpleNamespace(id='rep')
        body = SimpleNamespace(request_id='file', size=10, content_type='video/mp4')
        existing = SimpleNamespace(id='file', liveswitch_panel_visible=False)
        db = Mock()
        db.query.side_effect = AssertionError('Import must not read or rewrite report state')
        context.return_value = lead, existing, 'bucket', 'key', 'video.mp4'
        self.assertTrue(scope['prepare_panel_upload']('lead', body, user, db)['completed'])
        self.assertTrue(existing.liveswitch_panel_visible)
        context.return_value = lead, None, 'bucket', 'key', 'video.mp4'
        with patch.dict(sys.modules, {'models': SimpleNamespace(LeadAttachment=scope['LeadAttachment'])}):
            self.assertEqual(scope['finish_panel_upload']('lead', body, user, db), {'id': 'file'})
        self.assertEqual(db.commit.call_count, 2)
        archive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
