"""Temporary isolated interactive authorization for manual import support traces."""
import html
import json
import re
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException
from fastapi.responses import HTMLResponse


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {key: '[REDACTED]' if key.lower() in {
            'access_token','refresh_token','id_token','client_secret','code','state','authorization',
            'publicurl','thumbnailurl'} else redact(item, secrets) for key,item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        try:
            return redact(json.loads(value), secrets)
        except (ValueError, TypeError):
            for secret in secrets:
                if secret:
                    value = value.replace(secret, '[REDACTED]')
            return re.sub(r'https?://[^\s"<>]+\?[^\s"<>]+', '[SIGNED URL REDACTED]', value)
    return value


async def complete_import_login(request, code, state, error, error_description, state_data):
    from routes.liveswitch import _settings, TOKEN_URL, AUTHORIZE_URL, SCOPES, AUDIENCE
    client_id, client_secret, redirect_uri = _settings()
    trace = [{'stage':'authorization','request':{'method':'GET','url':AUTHORIZE_URL,
        'query':{'response_type':'code','client_id':client_id,'redirect_uri':redirect_uri,
        'scope':SCOPES,'audience':AUDIENCE,'prompt':'login consent','state':'[REDACTED]'}}},
        {'stage':'callback','request':{'method':'GET','path':request.url.path,
            'query':redact(dict(request.query_params), [code,state,client_secret])}}]
    payload = {'type':'liveswitch-import-result','trace':trace,'files':[]}
    try:
        if error or not code:
            raise HTTPException(400, error_description or error or 'Missing authorization code')
        body = {'grant_type':'authorization_code','code':code,'client_id':client_id,
                'client_secret':client_secret,'redirect_uri':redirect_uri}
        exchange = {'stage':'token exchange','request':{'method':'POST','url':TOKEN_URL,'body':redact(body)}}
        trace.append(exchange)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TOKEN_URL,json=body)
        exchange['response'] = {'status':response.status_code,'body':redact(response.text,[code,client_secret,state])}
        if not response.is_success:
            raise HTTPException(502, f'LiveSwitch token exchange HTTP {response.status_code}')
        tokens = response.json()
        access_token = tokens.get('access_token')
        if not access_token:
            raise HTTPException(502,'LiveSwitch did not return an access token')
        from database import SessionLocal
        from models import LeadLiveSwitch, User
        from routes.leads import _get_visible_lead_or_404, _ensure_not_dispatch_write
        from liveswitch_manual_import import missing_recordings, token_diagnostics
        # Never replace the shared OAuth connection or its token cache.
        with SessionLocal() as db:
            user = db.get(User,state_data['sub'])
            if not user:
                raise HTTPException(403,'CRM user is no longer available')
            _ensure_not_dispatch_write(user)
            lead = _get_visible_lead_or_404(state_data['import_lead_id'],user,db)
            saved = db.get(LeadLiveSwitch,lead.id)
            conversation = json.loads(saved.details or '{}') if saved else {}
            if not conversation.get('id'):
                raise HTTPException(409,'No conversation is saved for this lead')
            diagnostics = token_diagnostics(access_token)
            diagnostics['credential_source'] = 'fresh authorization-code exchange (import only)'
            trace.append({'stage':'fresh token claims','diagnostics':diagnostics})
            payload['files'] = missing_recordings(lead.id,conversation['id'],db,fresh_token=access_token,trace=trace)['files']
    except HTTPException as exc:
        payload['error'] = redact(exc.detail, [code,state,client_secret])
    except Exception as exc:
        payload['error'] = f'Import authorization failed: {type(exc).__name__}'
    safe = json.dumps(payload).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    uri = urlsplit(redirect_uri)
    origin = json.dumps(f'{uri.scheme}://{uri.netloc}')
    result = HTMLResponse('<!doctype html><title>LiveSwitch import</title>'
        '<p>Login check finished. Return to the CRM import panel.</p>'
        '<details><summary>Support trace (credentials redacted)</summary><pre>'
        + html.escape(json.dumps(trace,indent=2)) + '</pre></details>'
        + f'<script>if(window.opener){{window.opener.postMessage({safe},{origin});window.close();}}</script>',
        headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    result.delete_cookie('liveswitch_oauth_state',path='/api/liveswitch/oauth')
    return result
