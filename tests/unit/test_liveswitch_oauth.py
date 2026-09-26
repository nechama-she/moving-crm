"""OAuth setup tests with an in-memory SSM service; no credentials or network."""
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-signing-secret")
    monkeypatch.setenv("SSM_PREFIX", "/test/")
    source = Path(__file__).resolve().parents[2] / "backend/routes/liveswitch.py"
    tree = ast.parse(source.read_text(encoding="utf-8").split("# Lead conversation endpoints")[0])
    tree.body = [node for node in tree.body if not (isinstance(node, ast.ImportFrom) and node.module in {"auth", "config", "models"})]
    admin = lambda: SimpleNamespace(id="admin-1")
    config = {"client_id": "client", "client_secret": "secret", "redirect_uri": "https://crm.example/api/liveswitch/oauth/callback"}
    store = {"/test/LIVESWITCH_OAUTH_CONFIG": json.dumps(config)}
    ssm = MagicMock()

    def get_parameter(Name, **kwargs):
        if Name not in store:
            raise ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")
        return {"Parameter": {"Value": store[Name]}}

    ssm.get_parameter.side_effect = get_parameter
    ssm.put_parameter.side_effect = lambda Name, Value, **kwargs: store.update({Name: Value})
    ssm.delete_parameter.side_effect = lambda Name: store.pop(Name, None)
    scope = {"require_admin": admin, "User": SimpleNamespace, "get_config": lambda: {}, "_token_cache": {"value": "", "expires": 0}}
    exec(compile(tree, str(source), "exec"), scope)
    monkeypatch.setattr(scope["boto3"], "client", lambda *args, **kwargs: ssm)
    app = FastAPI()
    app.include_router(scope["router"])
    return SimpleNamespace(client=TestClient(app, base_url="https://crm.example"), scope=scope, store=store, ssm=ssm, config=config)


def test_status_does_not_disclose_secret_or_tokens(setup):
    setup.store["/test/LIVESWITCH_REFRESH_TOKEN"] = "private-refresh"
    response = setup.client.get("/api/liveswitch/settings")
    assert response.status_code == 200
    assert response.json() == {"client_id": "client", "redirect_uri": setup.config["redirect_uri"], "has_secret": True, "authorization_saved": True, "spark_template_id": ""}
    assert "private-refresh" not in response.text
    assert '"secret"' not in response.text


def test_saving_preserves_blank_secret_and_encrypts_configuration(setup):
    setup.store["/test/LIVESWITCH_REFRESH_TOKEN"] = "old-token"
    response = setup.client.put("/api/liveswitch/settings", json={**setup.config, "client_secret": "", "redirect_uri": "https://new.example/api/liveswitch/oauth/callback"})
    assert response.status_code == 200
    assert json.loads(setup.store["/test/LIVESWITCH_OAUTH_CONFIG"])["client_secret"] == "secret"
    assert setup.ssm.put_parameter.call_args.kwargs["Type"] == "SecureString"
    assert "/test/LIVESWITCH_REFRESH_TOKEN" not in setup.store


def test_new_client_requires_new_secret(setup):
    response = setup.client.put("/api/liveswitch/settings", json={**setup.config, "client_id": "new", "client_secret": ""})
    assert response.status_code == 400
    setup.ssm.put_parameter.assert_not_called()


@pytest.mark.parametrize("uri", ["http://example.com/api/liveswitch/oauth/callback", "https://example.com/wrong", "https://example.com/api/liveswitch/oauth/callback?x=1"])
def test_rejects_invalid_return_addresses(setup, uri):
    assert setup.client.put("/api/liveswitch/settings", json={**setup.config, "redirect_uri": uri}).status_code == 400


def test_unchanged_settings_keep_authorization(setup):
    setup.store["/test/LIVESWITCH_REFRESH_TOKEN"] = "existing"
    assert setup.client.put("/api/liveswitch/settings", json={**setup.config, "client_secret": ""}).status_code == 200
    setup.ssm.delete_parameter.assert_not_called()


def test_callback_requires_state_and_same_browser(setup):
    assert setup.client.get("/api/liveswitch/oauth/callback?code=abc").status_code == 400
    state = setup.scope["_create_state"]("admin-1")
    assert setup.client.get("/api/liveswitch/oauth/callback", params={"code": "abc", "state": state}).status_code == 400
    setup.ssm.put_parameter.assert_not_called()


def test_start_and_callback_save_refresh_token(setup, monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    response = setup.client.get("/api/liveswitch/oauth/start")
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert query["redirect_uri"] == [setup.config["redirect_uri"]]
    assert query['prompt'] == ['consent']
    assert query['scope'] == [setup.scope['SCOPES']]

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            assert json["client_secret"] == "secret"
            return SimpleNamespace(status_code=200, json=lambda: {"refresh_token": "new-refresh"})

    monkeypatch.setattr(setup.scope["httpx"], "AsyncClient", lambda **kwargs: FakeClient())
    result = setup.client.get("/api/liveswitch/oauth/callback", params={"code": "abc", "state": query["state"][0]})
    assert result.status_code == 200
    assert setup.store["/test/LIVESWITCH_REFRESH_TOKEN"] == "new-refresh"
    assert "new-refresh" not in result.text
    assert "liveswitch_oauth_state" not in setup.client.cookies


def test_settings_routes_require_admin(setup):
    from fastapi import HTTPException
    def denied(): raise HTTPException(403, "Admin only")
    setup.client.app.dependency_overrides[setup.scope["require_admin"]] = denied
    assert setup.client.get("/api/liveswitch/settings").status_code == 403
    assert setup.client.put("/api/liveswitch/settings", json=setup.config).status_code == 403
    assert setup.client.get("/api/liveswitch/oauth/start").status_code == 403


def test_fetch_and_extract_spark_report(monkeypatch):
    source = Path(__file__).resolve().parents[2] / "backend/routes/liveswitch.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "fetch_and_extract_spark_report")
    scope = {"httpx": MagicMock(), "re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)
    fetch_func = scope["fetch_and_extract_spark_report"]

    sample_data = {
        "structuredResult": {
            "sections": [
                {
                    "id": "item-list",
                    "rows": [
                        {"going": True, "quantity": 2, "unit_volume": 10.0, "unit_weight": 50.0},
                        {"going": False, "quantity": 1, "unit_volume": 100.0, "unit_weight": 500.0},
                        {"going": True, "quantity": 1, "unit_volume": 5.5, "unit_weight": 25.0},
                    ]
                }
            ]
        }
    }
    scope["httpx"].get.return_value = SimpleNamespace(status_code=200, json=lambda: sample_data)
    cuft, weight = fetch_func("https://app.scribe.liveswitch.com/public/reports/test-123")
    assert cuft == 25.5
    assert weight == 125.0
