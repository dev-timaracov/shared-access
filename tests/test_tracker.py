import pytest

from app.config import Settings
from app.schemas import ProjectCreate, TaskCreate
from app.trackers.factory import create_task_tracker
from app.worker import process_one


@pytest.mark.parametrize("app_client", ["memory"], indirect=True)
async def test_non_plane_adapter_context_transition_and_outbox(app_client):
    app, client, remote = app_client
    response = await client.post(
        "/api/projects",
        json={
            "slug": "demo",
            "name": "Demo",
            "tracker_provider": "memory",
            "tracker_workspace": "team",
            "tracker_project_id": "project-alpha",
            "repositories": ["team/payments"],
            "allowed_transitions": {"open": ["review"]},
        },
    )
    assert response.status_code == 201, response.text
    project = response.json()
    assert "plane_workspace" not in project
    response = await client.post(
        f"/api/projects/{project['id']}/tasks",
        json={
            "external_id": "TEAM-123",
        },
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["external_id"] == "TEAM-123"
    assert "plane_item_id" not in task
    url = f"/api/tasks/{task['id']}"
    response = await client.get(url + "/context", params={"repo": "team/payments", "ref": "main"})
    context = response.json()
    assert context["tracker"]["provider"] == "memory"
    assert context["tracker"]["snapshot"]["name"] == "Tracker-independent task"
    assert context["tracker"]["freshness"] == "live"
    assert "plane" not in context
    assert "Test adapter" in context["warnings"]
    response = await client.post(
        url + "/transitions",
        json={
            "expected_state_id": "open",
            "target_state_id": "review",
            "reason": "Ready for review",
        },
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = "Bearer alice"
    session = (
        await client.post(
            url + "/sessions",
            json={
                "agent_client": "codex",
                "repo": "team/payments",
                "branch": "feature/TEAM-123",
            },
        )
    ).json()
    response = await client.post(
        url + "/reports",
        json={
            "session_id": session["id"],
            "idempotency_key": "handoff-1",
            "outcome": "handoff",
            "summary": "Ready for next developer",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["tracker_sync"] == "queued"
    assert "plane_sync" not in response.json()
    assert await process_one(app.state.sessions, app.state.service.tracker)
    assert len(app.state.service.tracker.published) == 1
    assert "Ready for next developer" in app.state.service.tracker.published[0].content
    assert remote["requests"] == []


def test_legacy_request_aliases_and_settings():
    project = ProjectCreate(
        slug="demo",
        name="Demo",
        plane_workspace="team",
        plane_project_id="00000000-0000-0000-0000-000000000001",
    )
    assert project.tracker_workspace == "team"
    assert project.tracker_provider == "plane"
    assert TaskCreate(plane_item_id="TEAM-123").external_id == "TEAM-123"
    settings = Settings(auth_tokens={"test": {"developer_id": "test"}}, plane_sync_reports=True)
    assert settings.tracker_sync_reports is True


def test_unknown_adapter_fails_at_composition_boundary():
    settings = Settings(auth_tokens={"test": {"developer_id": "test"}}, task_tracker_provider="bad")
    with pytest.raises(ValueError, match="Unsupported task tracker"):
        create_task_tracker(settings, None)
