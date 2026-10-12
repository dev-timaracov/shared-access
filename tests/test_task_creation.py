import json
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.errors import ServiceError
from app.models import Task
from app.trackers.base import NewTask, TaskSnapshot, TaskTracker, TrackerProject
from app.trackers.plane import PlaneTaskTracker
from tests.conftest import row_count
from tests.test_plane import config


@pytest.mark.parametrize("version", ["v1", "v2"])
async def test_plane_create_contract(version):
    project = TrackerProject("team", str(uuid4()))
    external_id = str(uuid4())

    def remote(request):
        assert request.method == "POST"
        assert request.url.path == (
            f"/api/{version}/workspaces/team/projects/{project.project_id}/work-items/"
        )
        assert json.loads(request.content) == {
            "name": "New task",
            "description_html": "<p>&lt;script&gt;&amp;<br>second line</p>",
            "priority": "high",
        }
        return httpx.Response(201, json={"id": external_id, "name": "New task", "state": "open"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        task = await PlaneTaskTracker(config(version), http).create_task(
            project,
            NewTask(name="New task", description="<script>&\nsecond line", priority="high"),
        )
        assert task.id == external_id and task.state_id == "open"
        assert task.description_stripped == "<script>&\nsecond line"
        assert task.metadata["description_source"] == "creation_input"


@pytest.mark.parametrize("payload", [{}, [], {"id": "invalid"}])
async def test_plane_create_invalid_response(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(201, json=payload))
    ) as http:
        with pytest.raises(ServiceError, match="invalid created task"):
            await PlaneTaskTracker(config(), http).create_task(
                TrackerProject("team", str(uuid4())), NewTask(name="Task")
            )


@pytest.mark.parametrize("app_client", ["memory"], indirect=True)
async def test_creation_rest_mcp_scope_validation_and_failures(app_client, monkeypatch):
    app, client, remote = app_client
    project = (
        await client.post(
            "/api/projects",
            json={
                "slug": "demo",
                "name": "Demo",
                "tracker_provider": "memory",
                "tracker_workspace": "team",
                "tracker_project_id": "alpha",
            },
        )
    ).json()
    calls = []

    async def create(mapping, data):
        calls.append((mapping, data))
        return TaskSnapshot(id=f"TEAM-{len(calls)}", name=data.name, state_id="open")

    monkeypatch.setattr(app.state.service.tracker, "create_task", create)
    url = f"/api/projects/{project['id']}/tasks/create"
    for token, status in [("reader", 403), ("stranger", 404)]:
        client.headers["Authorization"] = f"Bearer {token}"
        assert (await client.post(url, json={"name": "Task"})).status_code == status
    assert not calls
    client.headers["Authorization"] = "Bearer alice"
    for body in [
        {"name": " "},
        {"name": "x" * 256},
        {"name": "Task", "state_id": "done"},
        {"name": "Task", "priority": "invalid"},
    ]:
        assert (await client.post(url, json=body)).status_code == 422
    assert not calls
    response = await client.post(url, json={"name": " New task ", "description": "Requirements"})
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["external_id"] == "TEAM-1" and task["freshness"] == "live"
    async with app.state.sessions() as db:
        stored = await db.scalar(select(Task).where(Task.id == task["id"]))
        assert stored.snapshot["name"] == "New task" and stored.fetched_at
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), headers={"Authorization": "Bearer alice"}
    ) as http:
        async with streamable_http_client("http://testserver/mcp/", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "create_task", {"project_id": project["id"], "task": {"name": "MCP task"}}
                )
                assert not result.isError
    assert await row_count(app, "tasks") == 2
    assert remote["requests"] == []

    async def fail(mapping, data):
        raise ServiceError(502, "Tracker unavailable")

    monkeypatch.setattr(app.state.service.tracker, "create_task", fail)
    assert (await client.post(url, json={"name": "Failure"})).status_code == 502
    assert await row_count(app, "tasks") == 2
    monkeypatch.setattr(app.state.service.tracker, "create_task", create)
    from sqlalchemy.ext.asyncio import AsyncSession

    async def fail_commit(self):
        raise OperationalError("commit", {}, Exception("Unavailable"))

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_commit)
        response = await client.post(url, json={"name": "Recoverable"})
    assert response.status_code == 503
    assert "TEAM-3" in response.json()["detail"]
    assert "do not repeat creation" in response.json()["detail"]
    assert await row_count(app, "tasks") == 2
    recovered = await client.post(
        f"/api/projects/{project['id']}/tasks", json={"external_id": "TEAM-3"}
    )
    assert recovered.status_code == 201


async def test_unsupported_creation_is_explicit():
    # Optional capability keeps existing third-party adapters usable.
    with pytest.raises(ServiceError, match="not supported"):
        await TaskTracker.create_task(None, TrackerProject("team", "project"), NewTask(name="x"))


@pytest.mark.parametrize("app_client", ["memory"], indirect=True)
async def test_creation_reuses_concurrently_registered_task(app_client, monkeypatch):
    app, client, remote = app_client
    project = (
        await client.post(
            "/api/projects",
            json={
                "slug": "demo",
                "name": "Demo",
                "tracker_provider": "memory",
                "tracker_workspace": "team",
                "tracker_project_id": "alpha",
            },
        )
    ).json()
    url = f"/api/projects/{project['id']}/tasks"
    assert (await client.post(url + "/create", json={"name": "Task"})).status_code == 501
    assert await row_count(app, "tasks") == 0
    registered = {}

    async def create(mapping, data):
        # Simulate sync/registration completing between upstream POST and local save.
        registered.update((await client.post(url, json={"external_id": "TEAM-new"})).json())
        return TaskSnapshot(id="TEAM-new", name=data.name)

    monkeypatch.setattr(app.state.service.tracker, "create_task", create)
    response = await client.post(url + "/create", json={"name": "New task"})
    assert response.status_code == 201, response.text
    assert response.json()["id"] == registered["id"]
    assert response.json()["snapshot"]["name"] == "New task"
    assert await row_count(app, "tasks") == 1
    assert remote["requests"] == []
