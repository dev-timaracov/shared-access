import asyncio
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr
from sqlalchemy import select, update

from app.models import Project, Report
from tests.conftest import row_count


def report(session, **changes):
    return {
        "session_id": session["id"],
        "idempotency_key": "milestone-1",
        "outcome": "handoff",
        "summary": "Payment retry implemented",
        "decisions": ["Use idempotency keys"],
        "next_steps": ["Review and QA"],
        "head_sha": "b" * 40,
        "commits": ["b" * 40],
        "checks": [{"command": "pytest", "result": "passed", "commit_sha": "b" * 40}],
        **changes,
    }


async def test_authentication_and_project_isolation(setup_task):
    _, client, _, project, task, session = setup_task
    client.headers.clear()
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/api/projects")).status_code == 401
    client.headers["Authorization"] = "Bearer stranger"
    assert (await client.get("/api/projects")).json() == []
    response = await client.get(
        f"/api/tasks/{task['id']}/context", params={"repo": "team/payments", "ref": "main"}
    )
    assert response.status_code == 404
    assert (
        await client.get(f"/api/projects/{project['id']}/search", params={"q": "retry"})
    ).status_code == 404
    client.headers["Authorization"] = "Bearer reader"
    assert (
        await client.post(f"/api/tasks/{task['id']}/reports", json=report(session))
    ).status_code == 403


async def test_report_idempotency_ownership_and_outbox(setup_task):
    app, client, remote, _, task, session = setup_task
    url = f"/api/tasks/{task['id']}/reports"
    response = await client.post(url, json=report(session))
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["report"]["developer_id"] == "alice"
    assert first["plane_sync"] == "queued"
    replay = await client.post(url, json=report(session))
    assert replay.json()["replayed"] is True
    assert replay.json()["report"]["id"] == first["report"]["id"]
    conflict = await client.post(url, json=report(session, summary="Changed report"))
    assert conflict.status_code == 409
    assert await row_count(app, "reports") == 1
    assert await row_count(app, "outbox") == 1
    assert await row_count(app, "git_links") == 2
    assert not remote["requests"]  # A report does not update Plane or publish synchronously.
    client.headers["Authorization"] = "Bearer bob"
    assert (await client.post(url, json=report(session))).status_code == 403


async def test_concurrent_identical_report_retries(setup_task):
    app, client, _, _, task, session = setup_task
    responses = await asyncio.gather(
        *[client.post(f"/api/tasks/{task['id']}/reports", json=report(session)) for _ in range(3)]
    )
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["report"]["id"] for r in responses}) == 1
    assert await row_count(app, "outbox") == 1


async def test_no_commit_handoff_and_invalid_sha(setup_task):
    _, client, _, _, task, session = setup_task
    url = f"/api/tasks/{task['id']}/reports"
    response = await client.post(
        url,
        json=report(
            session,
            head_sha=None,
            commits=[],
            dirty_worktree=True,
            artifact_url="https://git.example/team/payments/pull/1",
        ),
    )
    assert response.status_code == 201
    assert (await client.post(url, json=report(session, head_sha="short"))).status_code == 422
    assert (await client.post(url, json=report(session, developer_id="fake"))).status_code == 422


async def test_context_freshness_documents_and_fulltext(setup_task):
    _, client, remote, project, task, session = setup_task
    client.headers["Authorization"] = "Bearer admin"
    for ref, content in [("a" * 40, "Payment architecture retry"), ("main", "Wrong version")]:
        result = await client.put(
            f"/api/projects/{project['id']}/documents",
            json={
                "repo": "team/payments",
                "ref": ref,
                "path": "docs/agents/architecture.md",
                "content": content,
            },
        )
        assert result.status_code == 200, result.text
    client.headers["Authorization"] = "Bearer alice"
    await client.post(f"/api/tasks/{task['id']}/reports", json=report(session))
    params = {"repo": "team/payments", "ref": "a" * 40}
    url = f"/api/tasks/{task['id']}/context"
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["plane"]["freshness"] == "live"
    assert context["plane"]["snapshot"]["name"] == "Payment retry"
    assert context["plane"]["fetched_at"]
    assert len(context["documents"]) == 1
    doc = context["documents"][0]
    assert doc["excerpt"] == "Payment architecture retry"
    assert (await client.get(f"/api/documents/{doc['id']}")).json()["content"] == doc["excerpt"]
    search = await client.get(f"/api/projects/{project['id']}/search", params={"q": "retry"})
    assert len(search.json()["reports"]) == 1
    assert len(search.json()["documents"]) == 1
    exact = await client.get(
        f"/api/projects/{project['id']}/search",
        params={
            "q": "retry",
            "ref": "a" * 40,
        },
    )
    assert not exact.json()["reports"]
    remote["offline"] = True
    cached = (await client.get(url, params=params)).json()
    assert cached["plane"]["freshness"] == "cached"
    assert "Plane returned HTTP 503" in cached["warnings"]
    client.headers["Authorization"] = "Bearer stranger"
    assert (await client.get(f"/api/documents/{doc['id']}")).status_code == 404


async def test_unconfigured_plane_and_unknown_repository(setup_task):
    app, client, _, _, task, _ = setup_task
    app.state.service.settings.plane_api_key = SecretStr("")
    response = await client.get(
        f"/api/tasks/{task['id']}/context",
        params={
            "repo": "team/payments",
            "ref": "main",
        },
    )
    assert response.json()["plane"]["freshness"] == "unavailable"
    assert (
        await client.get(
            f"/api/tasks/{task['id']}/context",
            params={
                "repo": "foreign/repo",
                "ref": "main",
            },
        )
    ).status_code == 422


async def test_keyset_history(setup_task):
    _, client, _, _, task, session = setup_task
    for index in range(3):
        await client.post(
            f"/api/tasks/{task['id']}/reports",
            json=report(
                session,
                idempotency_key=f"step-{index}",
                summary=f"Step {index}",
            ),
        )
    url = f"/api/tasks/{task['id']}/history"
    first = (await client.get(url, params={"limit": 2})).json()
    second = (await client.get(url, params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert len(first["reports"]) == 2
    assert len(second["reports"]) == 1
    assert second["next_cursor"] is None
    assert len({r["id"] for r in first["reports"] + second["reports"]}) == 3
    assert (await client.get(url, params={"cursor": "broken"})).status_code == 422


async def test_transition_requires_admin_expected_state_and_allowlist(setup_task):
    app, client, remote, project, task, _ = setup_task
    target = str(uuid4())
    url = f"/api/tasks/{task['id']}/transitions"
    payload = {"expected_state_id": remote["state"], "target_state_id": target, "reason": "QA"}
    assert (await client.post(url, json=payload)).status_code == 403
    client.headers["Authorization"] = "Bearer admin"
    assert (await client.post(url, json=payload)).status_code == 403
    async with app.state.sessions() as db:
        await db.execute(
            update(Project)
            .where(Project.id == project["id"])
            .values(allowed_transitions={remote["state"]: [target]})
        )
        await db.commit()
    bad = await client.post(url, json={**payload, "expected_state_id": str(uuid4())})
    assert bad.status_code == 409
    result = await client.post(url, json=payload)
    assert result.status_code == 200, result.text
    assert remote["state"] == target
    assert await row_count(app, "task_events") == 1


async def test_real_mcp_protocol_and_identity_isolation(setup_task):
    app, _, _, project, task, _ = setup_task
    for token, expected in [("alice", 1), ("stranger", 0)]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {token}"},
        ) as http:
            async with streamable_http_client(
                "http://testserver/mcp/", http_client=http
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert "submit_work_report" in {t.name for t in tools.tools}
                    result = await session.call_tool("list_projects", {})
                    assert not result.isError
                    assert len(result.structuredContent["projects"]) == expected
                    result = await session.call_tool(
                        "get_task_context",
                        {
                            "task_id": task["id"],
                            "repo": "team/payments",
                            "ref": "main",
                        },
                    )
                    assert result.isError is (token == "stranger")
                    if token == "alice":
                        assert result.structuredContent["project"]["id"] == project["id"]
                        created = await session.call_tool(
                            "start_work_session",
                            {
                                "task_id": task["id"],
                                "session": {
                                    "agent_client": "claude",
                                    "repo": "team/payments",
                                    "branch": "feature/PAY-142-mcp",
                                    "base_sha": "a" * 40,
                                },
                            },
                        )
                        assert not created.isError
                        sent = await session.call_tool(
                            "submit_work_report",
                            {
                                "task_id": task["id"],
                                "report": report(created.structuredContent),
                            },
                        )
                        assert not sent.isError
                        assert sent.structuredContent["report"]["developer_id"] == "alice"


async def test_postgres_append_only_reports(setup_task):
    app, client, _, _, task, session = setup_task
    if app.state.engine.dialect.name != "postgresql":
        pytest.skip("Requires TEST_DATABASE_URL pointing to PostgreSQL")
    await client.post(f"/api/tasks/{task['id']}/reports", json=report(session))
    async with app.state.sessions() as db:
        item = await db.scalar(select(Report))
        with pytest.raises(Exception, match="append-only"):
            await db.execute(
                update(Report).where(Report.id == item.id).values(search_text="change")
            )


async def test_ready_checks_migrated_database(app_client):
    _, client, _ = app_client
    assert (await client.get("/health/ready")).status_code == 200
