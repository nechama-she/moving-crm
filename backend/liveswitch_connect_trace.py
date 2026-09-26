"""Display a redacted OAuth exchange for support, without storing credentials."""
import base64
import json
import re
from datetime import datetime, timezone

from fastapi.responses import HTMLResponse


class ConnectionTrace(list):
    def __init__(self, entries=()):
        super().__init__()
        for entry in entries:
            self.append(entry)

    def append(self, entry):
        super().append({'at_utc':datetime.now(timezone.utc).isoformat(),**entry})


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {key: '[REDACTED]' if key.lower() in {
            'code','state','client_secret','access_token','refresh_token','id_token',
            'authorization','cookie','set-cookie'} else redact(item,secrets) for key,item in value.items()}
    if isinstance(value, list):
        return [redact(item,secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value=value.replace(secret,'[REDACTED]')
        return re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+','[REDACTED JWT]',value)
    return value


def response_body(response, secrets=()):
    try:
        return redact(response.json(),secrets)
    except ValueError:
        return redact(response.text,secrets)


def token_claims(token):
    try:
        part=token.split('.')[1]
        claims=json.loads(base64.urlsafe_b64decode(part+'='*(-len(part)%4)))
        result = {key:claims[key] for key in ('scope','iat','exp','iss','aud') if key in claims}
        for key in ('iat','exp'):
            if isinstance(claims.get(key),(int,float)):
                result[key+'_utc']=datetime.fromtimestamp(claims[key],timezone.utc).isoformat()
        return result
    except (ValueError, TypeError, IndexError):
        return {'note':'Token is not a readable JWT; see token response scope.'}


def trace_page(trace, success, status=200):
    data=json.dumps(trace).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    title='LiveSwitch connected' if success else 'LiveSwitch connection failed'
    result=HTMLResponse(f'<!doctype html><title>{title}</title>'
        '<main style="font-family:system-ui;padding:24px;max-width:960px;margin:auto">'
        f'<h1>{title}</h1><p>Connection trace. Credentials are redacted.</p>'
        '<button id="copy" type="button">Copy support trace</button> <a href="/settings">Return to Settings</a>'
        '<p id="copy-status" role="status"></p><pre id="trace" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></main>'
        '<script>let prior=[];try{prior=JSON.parse(sessionStorage.getItem("liveswitch-connect-trace")||"[]");'
        'sessionStorage.removeItem("liveswitch-connect-trace");}catch{}'
        f'const text=JSON.stringify([...prior,...{data}],null,2);'
        'document.getElementById("trace").textContent=text;'
        'document.getElementById("copy").onclick=async()=>{try{await navigator.clipboard.writeText(text);'
        'document.getElementById("copy-status").textContent="Copied";}catch{'
        'document.getElementById("copy-status").textContent="Select the trace below to copy it.";}};</script>',
        status_code=status,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    result.delete_cookie('liveswitch_oauth_state',path='/api/liveswitch/oauth')
    return result
