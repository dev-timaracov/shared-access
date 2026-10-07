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
