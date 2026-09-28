"""Capture bounded error details for staff access history without changing responses."""
import json
from spark_processing import error_detail

LIMIT = 8000


def audit_body(body, content_type):
    if not body:
        return '[Empty body]'
    if len(body) > LIMIT:
        return '[Body omitted: exceeds 8000 bytes]'
    if 'json' not in content_type.lower():
        return '[Non-JSON body omitted]'
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return '[Invalid JSON body omitted]'
    def clean(value):
        if isinstance(value, dict):
            return {key: '[REDACTED]' if key.lower() in ('code', 'input', 'ctx') or any(part in key.lower().replace('-', '_')
                    for part in ('password', 'secret', 'token', 'authorization', 'cookie', 'api_key'))
                    else clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            return error_detail(RuntimeError(value)).removeprefix('RuntimeError: ')
        return value
    return json.dumps(clean(data), ensure_ascii=True, indent=2)


def exception_message(exc):
    nested = getattr(exc, 'exceptions', None)
    if nested:
        return '\n'.join(exception_message(item) for item in nested)[:LIMIT]
    return error_detail(exc)


def response_message(body):
    text = body.decode('utf-8', errors='replace')
    try:
        data = json.loads(text)
        detail = data.get('detail', data.get('message', data.get('error', ''))) if isinstance(data, dict) else data
        if isinstance(detail, list):
            # Validation errors can include submitted credentials in input/ctx.
            text = '; '.join(str(item.get('msg', 'Validation error')) if isinstance(item, dict) else str(item) for item in detail)
        elif isinstance(detail, dict):
            text = str(detail.get('message') or detail.get('detail') or detail.get('error') or 'API request failed')
        else:
            text = str(detail or 'API request failed')
    except (ValueError, TypeError):
        pass
    return error_detail(RuntimeError(text)).removeprefix('RuntimeError: ')


async def capture_response_error(response, capture_body=False):
    if response.status_code < 400 and not capture_body:
        return None
    content_type = response.headers.get('content-type', '').lower()
    if 'json' not in content_type and 'text/plain' not in content_type:
        if capture_body:
            response.audit_body = '[Non-JSON body omitted]'
        return f'HTTP {response.status_code}'
    if not hasattr(response, 'body_iterator'):
        if capture_body:
            response.audit_body = audit_body(response.body, content_type)
        return response_message(response.body[:LIMIT]) if response.status_code >= 400 else None
    iterator = response.body_iterator
    chunks = []
    size = 0
    async for chunk in iterator:
        chunks.append(chunk)
        size += len(chunk)
        if size > LIMIT:
            break
    async def replay():
        for chunk in chunks:
            yield chunk
        async for chunk in iterator:
            yield chunk
    response.body_iterator = replay()
    body = b''.join(chunk.encode('utf-8') if isinstance(chunk, str) else chunk for chunk in chunks)
    if capture_body:
        response.audit_body = audit_body(body, content_type)
    return response_message(body[:LIMIT]) if response.status_code >= 400 else None
