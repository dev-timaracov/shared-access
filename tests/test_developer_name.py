import pytest
from pydantic import ValidationError

from app.config import Identity, Settings
from app.worker import process_one
from tests.test_service import report


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_invalid_display_name(name):
    with pytest.raises(ValidationError):
        Identity(developer_id="admin", display_name=name)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_disabled=True, local_admin_display_name=name)


def test_display_name_trims_and_defaults():
    assert (
        Identity(developer_id="admin", display_name="  Иван Иванов  ").display_name == "Иван Иванов"
    )
    assert Identity(developer_id="admin").display_name is None


@pytest.mark.parametrize("app_client", ["memory"], indirect=True)
async def test_report_name_snapshot_and_publication(app_client):
    app, client, _ = app_client
    project = (
        await client.post(
            "/api/projects",
            json={
                "slug": "demo",
                "name": "Demo",
                "tracker_provider": "memory",
                "tracker_workspace": "team",
                "tracker_project_id": "project",
                "repositories": ["repo"],
            },
        )
    ).json()
    task = (
        await client.post(
            f"/api/projects/{project['id']}/tasks",
            json={
                "external_id": "TEAM-123",
            },
        )
    ).json()
    session = (
        await client.post(
            f"/api/tasks/{task['id']}/sessions",
            json={
                "agent_client": "codex",
                "repo": "repo",
                "branch": "main",
            },
        )
    ).json()
    url = f"/api/tasks/{task['id']}"
    actor = app.state.service.settings.auth_tokens["admin"]
    actor.display_name = "Иван Иванов"
    payload = report(session)
    first = await client.post(url + "/reports", json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["report"]["developer_name"] == "Иван Иванов"
    assert first.json()["report"]["developer_id"] == "admin"
    actor.display_name = "Новое имя"
    replay = (await client.post(url + "/reports", json=payload)).json()
    assert replay["replayed"]
    assert replay["report"] == first.json()["report"]
    history = (await client.get(url + "/history")).json()
    assert history["reports"][0]["developer_name"] == "Иван Иванов"
    context = (await client.get(url + "/context", params={"repo": "repo", "ref": "a" * 40})).json()
    assert context["recent_reports"][0]["developer_name"] == "Иван Иванов"
    assert await process_one(app.state.sessions, app.state.service.tracker)
    assert "Разработчик: Иван Иванов (admin)" in app.state.service.tracker.published[0].content
    actor.display_name = None
    unnamed = await client.post(url + "/reports", json=report(session, idempotency_key="unnamed"))
    assert unnamed.status_code == 201, unnamed.text
    assert unnamed.json()["report"]["developer_name"] is None
    assert await process_one(app.state.sessions, app.state.service.tracker)
    assert "Разработчик: admin\n" in app.state.service.tracker.published[1].content
