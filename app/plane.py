from urllib.parse import quote

import httpx

from app.config import Settings
from app.errors import ServiceError


class PlaneClient:
    """Small v1/v2 adapter. Credentials never enter tool parameters or responses."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    def item_path(self, project, task):
        workspace = quote(project.plane_workspace or "", safe="")
        return (
            f"/api/{self.settings.plane_api_version}/workspaces/{workspace}/"
            f"projects/{project.plane_project_id}/work-items/{task.plane_item_id}/"
        )

    async def request(self, method, path, **kwargs):
        if not self.settings.plane_api_key.get_secret_value():
            raise ServiceError(503, "Plane API key is not configured")
        try:
            response = await self.http.request(
                method,
                self.settings.plane_base_url.rstrip("/") + path,
                headers={"X-Api-Key": self.settings.plane_api_key.get_secret_value()},
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ServiceError(502, f"Plane returned HTTP {status}") from None
        except (httpx.RequestError, ValueError):
            raise ServiceError(502, "Plane is unavailable or returned invalid JSON") from None

    async def get_item(self, project, task):
        if not project.plane_project_id:
            raise ServiceError(503, "Plane project mapping is not configured")
        result = await self.request("GET", self.item_path(project, task))
        if not isinstance(result, dict) or str(result.get("id")) != task.plane_item_id:
            raise ServiceError(502, "Plane returned an unexpected work item")
        return result

    async def get_context_item(self, project, task):
        result = await self.get_item(project, task)
        warnings = []
        result["description_source"] = self.settings.plane_api_version
        if self.settings.plane_api_version == "v2":
            # v2 work-item reads omit the description. Use the documented v1 detail
            # endpoint when available, rather than silently returning no requirements.
            try:
                detail = await self.request(
                    "GET", self.item_path(project, task).replace("/api/v2/", "/api/v1/", 1)
                )
                if not isinstance(detail, dict) or str(detail.get("id")) != task.plane_item_id:
                    raise ServiceError(502, "Unexpected Plane description response")
                for field in ("description_html", "description_stripped"):
                    if field in detail:
                        result[field] = detail[field]
                result["description_source"] = "v1_fallback"
            except ServiceError:
                warnings.append("Plane v2 omits description; v1 requirements fallback unavailable")
                result["description_source"] = "unavailable"
        try:
            response = await self.request(
                "GET",
                self.item_path(project, task) + "comments/",
                params={"per_page": 10, "order_by": "-created_at"},
            )
            comments = response if isinstance(response, list) else response.get("results", [])
            result["comments"] = [
                {
                    key: comment[key]
                    for key in (
                        "id",
                        "comment_stripped",
                        "comment_html",
                        "created_at",
                        "actor",
                        "actor_id",
                    )
                    if key in comment
                }
                for comment in comments[:10]
            ]
        except (ServiceError, AttributeError, TypeError):
            warnings.append("Recent Plane comments unavailable")
        result["_context_warnings"] = warnings
        return result

    @staticmethod
    def state_id(snapshot):
        state = snapshot.get("state_id", snapshot.get("state"))
        if isinstance(state, dict):
            state = state.get("id")
        return str(state) if state else None

    async def transition(self, project, task, state_id):
        field = "state" if self.settings.plane_api_version == "v1" else "state_id"
        return await self.request("PATCH", self.item_path(project, task), json={field: state_id})

    async def publish_report(self, project, task, report, html):
        path = self.item_path(project, task) + "comments/"
        external_id = report.id
        params = {"external_id": external_id, "external_source": "project-context-service"}
        # Verify existence on every retry, including timeout-after-acceptance failures.
        cursor = None
        for _ in range(100):
            query = dict(params)
            if cursor:
                query["cursor"] = cursor
            response = await self.request("GET", path, params=query)
            comments = response if isinstance(response, list) else response.get("results", [])
            if any(
                c.get("external_id") == external_id
                and c.get("external_source") == params["external_source"]
                for c in comments
            ):
                return
            cursor = response.get("next_cursor") if isinstance(response, dict) else None
            if not cursor:
                break
        else:
            raise ServiceError(502, "Plane comment pagination exceeded safety limit")
        await self.request(
            "POST",
            path,
            json={
                "comment_html": html,
                "access": "INTERNAL",
                **params,
            },
        )
