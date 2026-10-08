import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from app.models import Task
from app.trackers.base import TaskPage, TaskSnapshot
from tests.conftest import row_count


@pytest.mark.parametrize("app_client", ["memory"], indirect=True)
async def test_init_sync_protocol_scope_and_retry(app_client):
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
                "repositories": ["team/repo"],
            },
        )
    ).json()
    url = f"/api/projects/{project['id']}"
    specification = {"repo": "team/repo", "ref": "a" * 40}
    for token, init_status, sync_status in [
        ("reader", 403, 403),
        ("alice", 403, 200),
        ("stranger", 403, 404),
    ]:
        client.headers["Authorization"] = f"Bearer {token}"
        assert (await client.post(url + "/init", json=specification)).status_code == init_status
        assert (await client.post(url + "/sync")).status_code == sync_status
    client.headers["Authorization"] = "Bearer admin"
    assert (
        await client.post(url + "/init", json={**specification, "ref": "main"})
    ).status_code == 422
    assert (
        await client.post(url + "/init", json={**specification, "repo": "x"})
    ).status_code == 422
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), headers={"Authorization": "Bearer admin"}
    ) as http:
        async with streamable_http_client("http://testserver/mcp/", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "init",
                    {
                        "project_id": project["id"],
                        "specification": specification,
                    },
                )
                assert not result.isError
                assert not (await session.call_tool("sync", {"project_id": project["id"]})).isError
    docs = (await client.post(url + "/init", json=specification)).json()["documents"]
    assert {d["path"] for d in docs} == {"testing.md", "agents.md", "architecture.md", "report.md"}
    assert all(not d["created"] for d in docs)
    await client.put(
        url + "/documents", json={**specification, "path": "testing.md", "content": "custom"}
    )
    await client.post(url + "/init", json=specification)
    assert (await client.get(f"/api/documents/{docs[0]['id']}")).json()["content"] == "custom"
    assert await row_count(app, "documents") == 4
    assert remote["requests"] == []

    calls = []

    async def pages(project, cursor=None, limit=20):
        calls.append(cursor)
        if cursor is None:
            return TaskPage([TaskSnapshot(id="TEAM-123", name="changed", state_id="done")], "next")
        return TaskPage([TaskSnapshot(id="TEAM-124", name="new")])

    app.state.service.tracker.list_tasks = pages
    result = (await client.post(url + "/sync")).json()
    assert calls == [None, "next"]
    assert result["created"] == 1 and result["updated"] == 1
    async with app.state.sessions() as db:
        task = await db.scalar(select(Task).where(Task.external_id == "TEAM-123"))
        assert task.snapshot["state_id"] == "done" and task.fetched_at
    assert (await client.post(url + "/sync")).json()["created"] == 0

    async def broken(project, cursor=None, limit=20):
        return TaskPage([TaskSnapshot(id="SHOULD-NOT-SAVE")], "loop")

    app.state.service.tracker.list_tasks = broken
    assert (await client.post(url + "/sync")).status_code == 502
    assert await row_count(app, "tasks") == 2
