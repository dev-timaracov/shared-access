import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.errors import ServiceError
from app.plane import PlaneClient


def config(version="v1"):
    return Settings(
        auth_tokens={"test": {"developer_id": "test", "role": "reader", "projects": []}},
        plane_api_key="fake",
        plane_api_version=version,
    )


@pytest.mark.parametrize("version,field", [("v1", "state"), ("v2", "state_id")])
async def test_plane_transition_request_fields(version, field):
    item_id, state = str(uuid4()), str(uuid4())
    project = SimpleNamespace(plane_workspace="team", plane_project_id=str(uuid4()))
    task = SimpleNamespace(plane_item_id=item_id)

    def remote(request):
        assert request.headers["X-Api-Key"] == "fake"
        assert f"/api/{version}/" in request.url.path
        assert json.loads(request.content) == {field: state}
        return httpx.Response(200, json={"id": item_id, field: state})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        result = await PlaneClient(config(version), http).transition(project, task, state)
        assert PlaneClient.state_id(result) == state


@pytest.mark.parametrize("fallback_available", [True, False])
async def test_v2_requirements_fallback_is_explicit(fallback_available):
    item_id = str(uuid4())
    project = SimpleNamespace(plane_workspace="team", plane_project_id=str(uuid4()))
    task = SimpleNamespace(plane_item_id=item_id)

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
        result = await PlaneClient(config("v2"), http).get_context_item(project, task)
        assert result["comments"][0]["comment_stripped"] == "QA pending"
        if fallback_available:
            assert result["description_html"] == "<p>Spec</p>"
            assert result["description_source"] == "v1_fallback"
            assert not result["_context_warnings"]
        else:
            assert result["description_source"] == "unavailable"
            assert result["_context_warnings"]


async def test_comment_retry_does_not_duplicate_remote_write():
    project = SimpleNamespace(plane_workspace="team", plane_project_id=str(uuid4()))
    task = SimpleNamespace(plane_item_id=str(uuid4()))
    report = SimpleNamespace(id=str(uuid4()))
    written = []

    def remote(request):
        if request.method == "POST":
            value = json.loads(request.content)
            written.append(value)
            # Simulate accepted POST whose response was lost.
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(200, json={"results": written})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        plane = PlaneClient(config(), http)
        with pytest.raises(ServiceError, match="unavailable"):
            await plane.publish_report(project, task, report, "<p>done</p>")
        await plane.publish_report(project, task, report, "<p>done</p>")
        assert len(written) == 1
