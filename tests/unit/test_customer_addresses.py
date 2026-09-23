import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import customer_addresses as addresses


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(addresses, 'get_config', lambda: {'GOOGLE_MAPS_SERVER_KEY':'private-provider-key'})
    monkeypatch.setenv('JWT_SECRET','test-secret-with-at-least-thirty-two-characters')
    parts=[{'types':[kind],'longText':value,'shortText':value} for kind,value in
           [('locality','Miami'),('administrative_area_level_1','FL'),('country','US')]]
    place={'id':'place1','formattedAddress':'Miami, FL, USA','addressComponents':parts}
    calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return httpx.Response(200,json=place,request=httpx.Request(method,url))
    monkeypatch.setattr(addresses.httpx,'request',request)
    return place,calls


def test_resolve_keeps_key_server_side_and_signs_selection(google):
    _,calls=google
    result=addresses.resolve_address('place1','session-token','access1')
    assert result['city']=='Miami'
    assert 'private-provider-key' not in str(result)
    assert calls[0][2]['headers']['X-Goog-Api-Key']=='private-provider-key'
    selection=SimpleNamespace(proof=result['proof'],model_dump=lambda **kw:{k:v for k,v in result.items() if k!='proof'})
    addresses.validate_selection(selection,'access1')
    with pytest.raises(HTTPException): addresses.validate_selection(selection,'other-access')
    result['city']='Forged'
    with pytest.raises(HTTPException): addresses.validate_selection(selection,'access1')


@pytest.mark.parametrize('missing',['locality','administrative_area_level_1','country'])
def test_incomplete_address_rejected(google,missing):
    place,_=google
    place['addressComponents']=[p for p in place['addressComponents'] if missing not in p['types']]
    with pytest.raises(HTTPException) as exc: addresses.resolve_address('place1','session-token','access1')
    assert exc.value.status_code==400


def test_provider_error_does_not_leak_key_or_body(google,monkeypatch):
    def request(method,url,**kwargs):
        return httpx.Response(403,json={'error':'private-provider-key secret message'},request=httpx.Request(method,url))
    monkeypatch.setattr(addresses.httpx,'request',request)
    with pytest.raises(HTTPException) as exc: addresses.suggestions('Miami','session-token')
    assert exc.value.status_code==502
    assert 'private-provider-key' not in str(exc.value.detail)


def test_missing_key_makes_no_provider_call(google,monkeypatch):
    _,calls=google
    monkeypatch.setattr(addresses,'get_config',lambda:{})
    monkeypatch.delenv('GOOGLE_MAPS_SERVER_KEY',raising=False)
    with pytest.raises(HTTPException) as exc: addresses.suggestions('Miami','session-token')
    assert exc.value.status_code==503
    assert calls==[]


def test_suggestions_return_only_display_fields(google,monkeypatch):
    def request(method,url,**kwargs):
        return httpx.Response(200,json={'suggestions':[{'placePrediction':{'placeId':'place1','text':{'text':'Miami, FL'},'extra':'ignored'}}]},request=httpx.Request(method,url))
    monkeypatch.setattr(addresses.httpx,'request',request)
    assert addresses.suggestions('Miami','session-token')==[{'place_id':'place1','text':'Miami, FL'}]
