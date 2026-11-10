"""After a customer page saves, its other open pages are told to update, and signatures tell the work queue too; reads
and failed saves tell no one."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
os.environ.setdefault('JWT_SECRET', 'test-only-secret-with-at-least-32-characters')

MOVE = '11111111-2222-3333-4444-555555555555'


def test_saves_announce_the_move_with_the_page_that_saved():
    import customer_page_announcements as announcements
    app = FastAPI()

    @app.api_route('/api/public-moves/{access_id}/{rest:path}', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    def endpoint(access_id: str, rest: str):
        if rest == 'fails':
            raise HTTPException(409, 'No')
        return {'ok': True}

    app.add_middleware(BaseHTTPMiddleware, dispatch=announcements.announce_customer_page_changes)
    sent, activity = [], []
    with patch.object(announcements, '_move_of', lambda id, link: ('lead', link == 'rep-key', 'Eli Jones' if link == 'rep-key' else 'Jane Doe') if id == MOVE else (None, False, '')), patch('realtime.publish_move_change', lambda *args: sent.append(args)),             patch('realtime.publish_realtime_event', activity.append):
        client = TestClient(app)
        client.post(f'/api/public-moves/{MOVE}/estimate-signatures/abc/sign', headers={'x-page-id': 'page-1'})
        client.post(f'/api/public-moves/{MOVE}/packing', headers={'x-public-link': 'rep-key'})
        client.post(f'/api/public-moves/{MOVE}/estimate-signatures')
        client.post(f'/api/public-moves/{MOVE}/recalculate-price', headers={'x-automatic': '1'})
        client.patch(f'/api/public-moves/{MOVE}/inventory/actions')
        client.post(f'/api/public-moves/{MOVE}/bill-of-lading/1/rev/sign')
        client.post(f'/api/public-moves/{MOVE}/estimate-signatures/abc/resign')
        for read in ('mileage', 'verify', 'realtime-token', 'prepare-upload'):
            client.post(f'/api/public-moves/{MOVE}/{read}')
        client.get(f'/api/public-moves/{MOVE}/details')
        client.post(f'/api/public-moves/{MOVE}/fails')
        client.post('/api/public-moves/22222222-2222-3333-4444-555555555555/files')
    assert sent == [('lead', 'page-1', 'estimate_signed', 'customer', 'Jane Doe'), ('lead', '', 'packing_changed', 'team', 'Eli Jones'),
                    ('lead', '', '', 'customer', 'Jane Doe'), ('lead', '', '', 'customer', 'Jane Doe'),
                    ('lead', '', 'inventory_updated', 'customer', 'Jane Doe'),
                    ('lead', '', 'bill_of_lading_signed', 'customer', 'Jane Doe'),
                    ('lead', '', 'estimate_signature_cancelled', 'customer', 'Jane Doe')]
    assert activity == [{'type': 'customer_activity', 'lead_id': 'lead'}] * 3
