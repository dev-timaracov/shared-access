import json
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.errors import ServiceError
from app.trackers.base import TrackerProject, TrackerReport
from app.trackers.plane import PlaneTaskTracker


def config(version="v1"):
    return Settings(
        auth_tokens={"test": {"developer_id": "test", "role": "reader", "projects": []}},
        plane_api_key="fake",
        plane_api_version=version,
    )


@pytest.mark.parametrize("version", ["v1", "v2"])
async def test_list_tasks_pagination(version):
    project = TrackerProject("team", str(uuid4()))
    item_id = str(uuid4())

    def remote(request):
        assert request.url.path.endswith(f"/projects/{project.project_id}/work-items/")
        assert f"/api/{version}/" in request.url.path
        assert request.url.params["per_page"] == "1"
        if request.url.params.get("cursor") == "page-2":
            return httpx.Response(
                200,
                json={
                    "results": [],
                    "next_cursor": "unused",
                    "next_page_results": False,
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [{"id": item_id, "name": "Existing task", "state": {"id": "open"}}],
                "next_cursor": "page-2",
                "next_page_results": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        tracker = PlaneTaskTracker(config(version), http)
        page = await tracker.list_tasks(project, limit=1)
        assert page.tasks[0].id == item_id
        assert page.tasks[0].state_id == "open"
        assert page.next_cursor == "page-2"
        last = await tracker.list_tasks(project, page.next_cursor, 1)
        assert last.tasks == []
        assert last.next_cursor is None


@pytest.mark.parametrize("payload", [{}, {"results": [{}]}, {"results": "bad"}])
async def test_list_tasks_rejects_invalid_pages(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload),
        )
    ) as http:
        with pytest.raises(ServiceError, match="invalid task page"):
            await PlaneTaskTracker(config(), http).list_tasks(TrackerProject("team", str(uuid4())))


@pytest.mark.parametrize("version,field", [("v1", "state"), ("v2", "state_id")])
async def test_plane_transition_request_fields(version, field):
    item_id, state = str(uuid4()), str(uuid4())
    project = TrackerProject("team", str(uuid4()))

    def remote(request):
        assert request.headers["X-Api-Key"] == "fake"
        assert f"/api/{version}/" in request.url.path
        assert json.loads(request.content) == {field: state}
        return httpx.Response(200, json={"id": item_id, field: state})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        result = await PlaneTaskTracker(config(version), http).transition_task(
            project, item_id, state
        )
        assert result.state_id == state


@pytest.mark.parametrize("fallback_available", [True, False])
async def test_v2_requirements_fallback_is_explicit(fallback_available):
    item_id = str(uuid4())
    project = TrackerProject("team", str(uuid4()))

    def remote(request):
        if request.url.path.endswith("comments/"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "comment-1",
                            "comment_stripped": "QA pending",
                        }
                    ]
                },
            )
        if "/v1/" in request.url.path:
            return (
                httpx.Response(200, json={"id": item_id, "description_html": "<p>Spec</p>"})
                if fallback_available
                else httpx.Response(404)
            )
        return httpx.Response(200, json={"id": item_id, "state_id": str(uuid4())})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        result = await PlaneTaskTracker(config("v2"), http).get_task_context(project, item_id)
        assert result.snapshot.comments[0]["text"] == "QA pending"
        if fallback_available:
            assert result.snapshot.description_html == "<p>Spec</p>"
            assert result.snapshot.metadata["description_source"] == "v1_fallback"
            assert not result.warnings
        else:
            assert result.snapshot.metadata["description_source"] == "unavailable"
            assert result.warnings


async def test_comment_retry_does_not_duplicate_remote_write():
    project = TrackerProject("team", str(uuid4()))
    task = str(uuid4())
    report = TrackerReport(str(uuid4()), "done")
    written = []

    def remote(request):
        if request.method == "POST":
            value = json.loads(request.content)
            written.append(value)
            # Simulate accepted POST whose response was lost.
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(200, json={"results": written})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        plane = PlaneTaskTracker(config(), http)
        with pytest.raises(ServiceError, match="unavailable"):
            await plane.publish_report(project, task, report)
        await plane.publish_report(project, task, report)
        assert len(written) == 1


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("empty_page", [True, False])
async def test_report_publishes_after_final_page_with_nonempty_cursor(version, empty_page):
    project = TrackerProject("team", str(uuid4()))
    task = str(uuid4())
    report = TrackerReport(str(uuid4()), "<done>")
    calls = []
    written = []

    def remote(request):
        calls.append(request.method)
        if request.method == "POST":
            written.append(json.loads(request.content))
            return httpx.Response(201, json=written[-1])
        assert "cursor" not in request.url.params
        return httpx.Response(
            200,
            json={
                "results": [] if empty_page else [{"external_id": "another-report"}],
                "next_cursor": "1000:1:0",
                "next_page_results": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        await PlaneTaskTracker(config(version), http).publish_report(project, task, report)
    assert calls == ["GET", "POST"]
    assert written[0]["external_id"] == report.id
    assert written[0]["comment_html"] == "<pre>&lt;done&gt;</pre>"


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("already_published", [True, False])
async def test_report_searches_next_page_before_publishing(version, already_published):
    project = TrackerProject("team", str(uuid4()))
    task = str(uuid4())
    report = TrackerReport(str(uuid4()), "done")
    calls = []

    def remote(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json=json.loads(request.content))
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(
                200,
                json={"results": [], "next_cursor": "page-2", "next_page_results": True},
            )
        assert cursor == "page-2"
        matching = {"external_id": report.id, "external_source": "project-context-service"}
        return httpx.Response(
            200,
            json={
                "results": [matching] if already_published else [],
                "next_cursor": "page-3",
                "next_page_results": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        await PlaneTaskTracker(config(version), http).publish_report(project, task, report)
    assert calls == (["GET", "GET"] if already_published else ["GET", "GET", "POST"])
