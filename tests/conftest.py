import asyncio
import json
import os
import sys
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from app.config import Settings
from app.main import create_app
from tests.fakes import MemoryTracker


@pytest.fixture
async def app_client(tmp_path, monkeypatch, request):
    database = os.getenv("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    tokens = {
        "admin": {"developer_id": "admin", "role": "admin", "projects": ["*"]},
        "alice": {"developer_id": "alice", "role": "writer", "projects": ["demo"]},
        "bob": {"developer_id": "bob", "role": "writer", "projects": ["demo"]},
        "reader": {"developer_id": "reader", "role": "reader", "projects": ["demo"]},
        "stranger": {"developer_id": "stranger", "role": "writer", "projects": ["other"]},
    }
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.setenv("AUTH_TOKENS", json.dumps(tokens))
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "head",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stdout.decode() + stderr.decode()
    remote = {"requests": [], "item_id": None, "state": str(uuid4()), "offline": False}

    def plane(request):
        remote["requests"].append(request)
        if remote["offline"]:
            return httpx.Response(503)
        if request.method == "PATCH":
            body = json.loads(request.content)
            remote["state"] = body.get("state", body.get("state_id"))
        return httpx.Response(
            200,
            json={
                "id": remote["item_id"],
                "name": "Payment retry",
                "state": remote["state"],
                "description_html": "<p>Retry safely</p>",
                "priority": "high",
            },
        )

    settings = Settings(
        database_url=database, auth_tokens=tokens, plane_api_key="fake-key", plane_sync_reports=True
    )
    plane_http = httpx.AsyncClient(transport=httpx.MockTransport(plane))
    tracker = MemoryTracker() if getattr(request, "param", None) == "memory" else None
    app = create_app(settings, http=plane_http, tracker=tracker)
    started, stopped = asyncio.Event(), asyncio.Event()

    async def lifespan_task():
        async with app.router.lifespan_context(app):
            started.set()
            await stopped.wait()

    background = asyncio.create_task(lifespan_task())
    await asyncio.wait_for(started.wait(), timeout=10)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer admin"},
        ) as client:
            yield app, client, remote
    finally:
        # Test data only: make non-Plane mappings compatible with the guarded downgrade.
        if tracker is not None:
            async with app.state.sessions() as db:
                await db.execute(text("UPDATE projects SET tracker_provider = 'plane'"))
                await db.commit()
        stopped.set()
        await background
    await plane_http.aclose()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "downgrade",
        "base",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stdout.decode() + stderr.decode()


@pytest.fixture
async def setup_task(app_client):
    app, client, remote = app_client
    project_data = {
        "slug": "demo",
        "name": "Demo",
        "repositories": ["team/payments"],
        "plane_workspace": "team",
        "plane_project_id": str(uuid4()),
    }
    response = await client.post("/api/projects", json=project_data)
    assert response.status_code == 201, response.text
    project = response.json()
    item_id = str(uuid4())
    remote["item_id"] = item_id
    response = await client.post(
        f"/api/projects/{project['id']}/tasks", json={"plane_item_id": item_id}
    )
    assert response.status_code == 201, response.text
    task = response.json()
    client.headers["Authorization"] = "Bearer alice"
    response = await client.post(
        f"/api/tasks/{task['id']}/sessions",
        json={
            "agent_client": "codex",
            "repo": "team/payments",
            "branch": "feature/PAY-142",
            "base_sha": "a" * 40,
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()
    return app, client, remote, project, task, session


async def row_count(app, table):
    async with app.state.sessions() as db:
        return await db.scalar(text(f"SELECT count(*) FROM {table}"))
