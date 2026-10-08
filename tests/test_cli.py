import sys

import httpx
import pytest
from pydantic import ValidationError

from app.__main__ import main
from app.auth import AuthMiddleware, current_identity, identity_context
from app.config import Settings


def test_auth_requires_tokens_by_default():
    with pytest.raises(ValidationError, match="AUTH_TOKENS"):
        Settings(_env_file=None, auth_tokens={}, auth_disabled=False)
    assert Settings(_env_file=None, auth_tokens={}, auth_disabled=True).auth_disabled


@pytest.mark.parametrize("disabled", [False, True])
def test_cli(monkeypatch, tmp_path, disabled):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTH_TOKENS", "{}")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setattr(sys, "argv", ["app", *(["--no-auth"] if disabled else [])])
    captured = {}
    monkeypatch.setattr("app.__main__.create_app", lambda settings: settings)
    monkeypatch.setattr(
        "app.__main__.uvicorn.run", lambda app, **kw: captured.update(app=app, **kw)
    )
    if disabled:
        main()
        assert captured["app"].auth_disabled
        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8000
    else:
        with pytest.raises(ValidationError, match="AUTH_TOKENS"):
            main()


@pytest.mark.parametrize("path", ["/api/projects", "/mcp/"])
@pytest.mark.parametrize("disabled", [False, True])
async def test_auth_boundary(path, disabled):
    async def endpoint(scope, receive, send):
        actor = current_identity()
        assert actor.developer_id == "local-admin"
        assert actor.role == "admin"
        assert actor.projects == ["*"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AuthMiddleware(endpoint, tokens={}, auth_disabled=disabled)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(path)
        assert response.status_code == (200 if disabled else 401)
    assert identity_context.get() is None
