import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.conftest import row_count


async def test_task_listing_upstream_failure_and_scope(setup_task):
    _, client, remote, project, _, _ = setup_task
    url = f"/api/projects/{project['id']}"
    client.headers["Authorization"] = "Bearer stranger"
    assert (await client.get(url + "/tasks")).status_code == 404
    assert remote["requests"] == []
    client.headers["Authorization"] = "Bearer admin"
    remote["offline"] = True
    assert (await client.get(url + "/tasks")).status_code == 502
    remote["requests"].clear()
    client.headers["Authorization"] = "Bearer reader"
    assert (await client.get(url + "/tasks", params={"cursor": ""})).status_code == 422


@pytest.mark.parametrize("app_client", ["memory"], indirect=True)
async def test_project_repositories_and_live_tasks(app_client):
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
                "repositories": ["team/old"],
            },
        )
    ).json()
    url = f"/api/projects/{project['id']}"
    for _ in range(2):
        response = await client.post(
            url + "/repositories",
            json={
                "repositories": ["team/new", "team/new"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["repositories"] == ["team/old", "team/new"]
    assert (await client.get("/api/projects")).json()[0]["repositories"] == [
        "team/old",
        "team/new",
    ]
    assert (await client.post(url + "/repositories", json={"repositories": []})).status_code == 422
    assert (
        await client.post(
            url + "/repositories",
            json={
                "repositories": [f"team/repo-{i}" for i in range(30)],
            },
        )
    ).status_code == 422
    client.headers["Authorization"] = "Bearer reader"
    response = await client.get(url + "/tasks")
    assert response.status_code == 200, response.text
    assert response.json()["tasks"][0]["id"] == "TEAM-123"
    assert response.json()["freshness"] == "live"
    assert await row_count(app, "tasks") == 0
    assert remote["requests"] == []
    assert (await client.get(url + "/tasks", params={"limit": 101})).status_code == 422
    assert (
        await client.post(url + "/repositories", json={"repositories": ["x"]})
    ).status_code == 403
    client.headers["Authorization"] = "Bearer stranger"
    assert (await client.get(url + "/tasks")).status_code == 404

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        headers={"Authorization": "Bearer admin"},
    ) as http:
        async with streamable_http_client("http://testserver/mcp/", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "add_project_repositories",
                    {
                        "project_id": project["id"],
                        "repositories": ["team/mcp"],
                    },
                )
                assert not result.isError
                result = await session.call_tool(
                    "list_tracker_tasks", {"project_id": project["id"]}
                )
                assert not result.isError
    assert (
        "team/mcp"
        in (
            await client.get(
                "/api/projects",
                headers={
                    "Authorization": "Bearer admin",
                },
            )
        ).json()[0]["repositories"]
    )
