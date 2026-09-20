import ast
import asyncio
import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from access_errors import capture_response_error, exception_message, response_message
from models import AccessAuditLog


def test_error_capture_does_not_change_streamed_response():
    async def check():
        payload = b'{"detail":"Not authenticated"}'
        async def chunks():
            yield payload[:10]
            yield payload[10:]
        response = StreamingResponse(chunks(), status_code=401, media_type='application/json')
        assert await capture_response_error(response) == 'Not authenticated'
        assert b''.join([part async for part in response.body_iterator]) == payload
    asyncio.run(check())


def test_large_error_response_is_replayed_completely():
    async def check():
        payload = b'x' * 20000
        async def chunks():
            for offset in range(0, len(payload), 1000):
                yield payload[offset:offset + 1000]
        response = StreamingResponse(chunks(), status_code=500, media_type='text/plain')
        assert len(await capture_response_error(response)) <= 3000
        assert b''.join([part async for part in response.body_iterator]) == payload
    asyncio.run(check())


def test_validation_errors_do_not_log_submitted_values():
    body = b'{"detail":[{"msg":"Invalid password","input":"secretvalue","ctx":{"password":"private"}}]}'
    assert response_message(body) == 'Invalid password'
    assert 'secretvalue' not in exception_message(RuntimeError('token=secretvalue'))


def test_middleware_records_api_errors_and_unhandled_exceptions():
    node = next(n for n in ast.parse((BACKEND / 'main.py').read_text(encoding='utf-8')).body if getattr(n, 'name', '') == 'track_access_history')
    node.decorator_list = []
    db = MagicMock()
    scope = {'Request': Request, 'time': time, 'uuid4': uuid4, 'AccessAuditLog': AccessAuditLog,
             'SessionLocal': lambda: db, 'logger': logging.getLogger('audit-test'),
             '_extract_request_user': lambda req: (None, 'Anonymous', None, 'anonymous'),
             '_extract_client_ip': lambda req: '127.0.0.1',
             'capture_response_error': capture_response_error, 'exception_message': exception_message}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<access-middleware>', 'exec'), scope)
    app = FastAPI()
    app.middleware('http')(scope['track_access_history'])
    @app.get('/denied')
    def denied():
        return JSONResponse({'detail': 'Not authenticated'}, status_code=401)
    @app.get('/broken')
    def broken():
        raise ValueError('Missing pricing configuration')
    @app.get('/ok')
    def ok():
        return {'ok': True}
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/denied')
        assert response.status_code == 401
        assert response.json() == {'detail': 'Not authenticated'}
        row = db.add.call_args.args[0]
        assert row.error_message == 'Not authenticated'
        assert row.to_dict()['error_message'] == 'Not authenticated'
        response = client.get('/broken')
        assert response.status_code == 500
        assert response.text == 'Internal Server Error'
        row = db.add.call_args.args[0]
        assert row.status_code == 500
        assert 'Missing pricing configuration' in row.error_message
        assert client.get('/ok').json() == {'ok': True}
        assert db.add.call_args.args[0].error_message is None
