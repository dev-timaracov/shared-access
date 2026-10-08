import html
from urllib.parse import quote
from uuid import UUID

import httpx

from app.config import Settings
from app.errors import ServiceError
from app.trackers.base import (
    TaskContext,
    TaskPage,
    TaskSnapshot,
    TaskTracker,
    TrackerProject,
    TrackerReport,
)


class PlaneTaskTracker(TaskTracker):
    """Plane v1/v2 adapter; HTTP, UUID rules and response shapes stay here."""

    provider = "plane"

    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    def validate_project(self, project: TrackerProject) -> None:
        try:
            UUID(project.project_id)
        except ValueError:
            raise ServiceError(422, "Plane project id must be a UUID") from None

    def validate_external_id(self, external_id: str) -> None:
        try:
            UUID(external_id)
        except ValueError:
            raise ServiceError(422, "Plane task id must be a UUID") from None

    def item_path(self, project: TrackerProject, external_id: str) -> str:
        return (
            f"/api/{self.settings.plane_api_version}/workspaces/"
            f"{quote(project.workspace, safe='')}/projects/"
            f"{quote(project.project_id, safe='')}/work-items/{quote(external_id, safe='')}/"
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
            raise ServiceError(502, f"Plane returned HTTP {exc.response.status_code}") from None
        except (httpx.RequestError, ValueError):
            raise ServiceError(502, "Plane is unavailable or returned invalid JSON") from None

    @staticmethod
    def normalize(raw, external_id) -> TaskSnapshot:
        if not isinstance(raw, dict) or str(raw.get("id")) != external_id:
            raise ServiceError(502, "Plane returned an unexpected work item")
        state = raw.get("state_id", raw.get("state"))
        assignees = raw.get("assignee_ids", raw.get("assignees", []))
        parent = raw.get("parent_id", raw.get("parent"))
        return TaskSnapshot(
            id=external_id,
            name=raw.get("name", ""),
            state_id=str(state["id"] if isinstance(state, dict) else state) if state else None,
            description_html=raw.get("description_html"),
            description_stripped=raw.get("description_stripped"),
            priority=raw.get("priority"),
            identifier=raw.get("identifier"),
            assignee_ids=[str(a["id"] if isinstance(a, dict) else a) for a in assignees],
            parent_id=str(parent["id"] if isinstance(parent, dict) else parent) if parent else None,
            updated_at=raw.get("updated_at"),
        )

    async def list_tasks(self, project, cursor=None, limit=20) -> TaskPage:
        self.validate_project(project)
        path = self.item_path(project, "").removesuffix("/")
        response = await self.request(
            "GET",
            path,
            params={"per_page": limit, **({"cursor": cursor} if cursor else {})},
        )
        rows = (
            response
            if isinstance(response, list)
            else (response.get("results") if isinstance(response, dict) else None)
        )
        if not isinstance(rows, list) or len(rows) > limit:
            raise ServiceError(502, "Plane returned an invalid task page")
        tasks = []
        for row in rows:
            try:
                external_id = str(UUID(row["id"]))
                tasks.append(self.normalize(row, external_id))
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ServiceError(502, "Plane returned an invalid task page") from None
        next_cursor = None
        if isinstance(response, dict) and response.get("next_page_results") is not False:
            next_cursor = response.get("next_cursor")
            if next_cursor is not None and (
                not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor
            ):
                raise ServiceError(502, "Plane returned an invalid task cursor")
        return TaskPage(tasks, next_cursor)

    async def get_task(self, project: TrackerProject, external_id: str) -> TaskSnapshot:
        self.validate_project(project)
        self.validate_external_id(external_id)
        raw = await self.request("GET", self.item_path(project, external_id))
        return self.normalize(raw, external_id)

    async def get_task_context(self, project: TrackerProject, external_id: str) -> TaskContext:
        snapshot = await self.get_task(project, external_id)
        warnings = []
        snapshot.metadata["description_source"] = self.settings.plane_api_version
        if self.settings.plane_api_version == "v2":
            try:
                detail = await self.request(
                    "GET", self.item_path(project, external_id).replace("/api/v2/", "/api/v1/", 1)
                )
                normalized = self.normalize(detail, external_id)
                snapshot.description_html = normalized.description_html
                snapshot.description_stripped = normalized.description_stripped
                snapshot.metadata["description_source"] = "v1_fallback"
            except ServiceError:
                warnings.append("Plane v2 omits description; v1 requirements fallback unavailable")
                snapshot.metadata["description_source"] = "unavailable"
        try:
            response = await self.request(
                "GET",
                self.item_path(project, external_id) + "comments/",
                params={"per_page": 10, "order_by": "-created_at"},
            )
            comments = response if isinstance(response, list) else response.get("results", [])
            snapshot.comments = [
                {
                    "id": comment.get("id"),
                    "text": comment.get("comment_stripped"),
                    "html": comment.get("comment_html"),
                    "created_at": comment.get("created_at"),
                    "author": comment.get("actor_id", comment.get("actor")),
                }
                for comment in comments[:10]
            ]
        except (ServiceError, AttributeError, TypeError):
            warnings.append("Recent Plane comments unavailable")
        return TaskContext(snapshot, tuple(warnings))

    async def transition_task(
        self,
        project: TrackerProject,
        external_id: str,
        state_id: str,
    ) -> TaskSnapshot:
        self.validate_project(project)
        self.validate_external_id(external_id)
        try:
            UUID(state_id)
        except ValueError:
            raise ServiceError(422, "Plane state id must be a UUID") from None
        field = "state" if self.settings.plane_api_version == "v1" else "state_id"
        raw = await self.request(
            "PATCH",
            self.item_path(project, external_id),
            json={field: state_id},
        )
        return self.normalize(raw, external_id)

    async def publish_report(
        self,
        project: TrackerProject,
        external_id: str,
        report: TrackerReport,
    ) -> None:
        self.validate_project(project)
        self.validate_external_id(external_id)
        path = self.item_path(project, external_id) + "comments/"
        params = {"external_id": report.id, "external_source": "project-context-service"}
        cursor = None
        for _ in range(100):
            query = {**params, **({"cursor": cursor} if cursor else {})}
            response = await self.request("GET", path, params=query)
            comments = response if isinstance(response, list) else response.get("results", [])
            if any(
                c.get("external_id") == report.id
                and c.get("external_source") == params["external_source"]
                for c in comments
            ):
                return
            # Plane can return a next_cursor even on the final (including empty) page.
            if isinstance(response, dict) and response.get("next_page_results") is False:
                break
            cursor = response.get("next_cursor") if isinstance(response, dict) else None
            if not cursor:
                break
        else:
            raise ServiceError(502, "Plane comment pagination exceeded safety limit")
        await self.request(
            "POST",
            path,
            json={
                "comment_html": f"<pre>{html.escape(report.content)}</pre>",
                "access": "INTERNAL",
                **params,
            },
        )
