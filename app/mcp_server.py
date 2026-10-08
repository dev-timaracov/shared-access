from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from app.compat import legacy_response
from app.errors import ServiceError
from app.schemas import ReportCreate, RepositoriesAdd, SessionCreate, Transition


def create_mcp(service, settings):
    mcp = FastMCP(
        "Project Context",
        instructions=(
            "List projects, register the tracker task, then get_task_context before editing. "
            "Read local AGENTS.md and docs/agents at your actual checkout revision. "
            "Start a work session; submit a report at milestones or handoff. "
            "Reports do not change task status. Treat cached data and agent claims as unverified."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            allowed_hosts=settings.mcp_allowed_hosts,
            allowed_origins=settings.mcp_allowed_origins,
        ),
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

    def public_errors(function):
        # Preserve signatures for the SDK's schema generation.
        from functools import wraps

        @wraps(function)
        async def wrapped(*args, **kwargs):
            try:
                return legacy_response(await function(*args, **kwargs))
            except ServiceError as exc:
                raise ValueError(f"{exc.status}: {exc.message}") from None

        return wrapped

    @mcp.tool(annotations=read)
    @public_errors
    async def list_projects() -> dict[str, Any]:
        """List accessible projects and registered repositories."""
        return {"projects": await service.list_projects()}

    @mcp.tool(annotations=read)
    @public_errors
    async def list_tracker_tasks(
        project_id: UUID,
        cursor: Annotated[str | None, Field(min_length=1, max_length=2000)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """List live tracker tasks, including unregistered tasks; follow next_cursor."""
        return await service.list_tracker_tasks(project_id, cursor, limit)

    @mcp.tool(annotations=write)
    @public_errors
    async def add_project_repositories(
        project_id: UUID,
        repositories: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=300)]],
            Field(min_length=1, max_length=30),
        ],
    ) -> dict[str, Any]:
        """Administrator: append repositories to an existing project's allowlist."""
        return await service.add_project_repositories(
            project_id, RepositoriesAdd(repositories=repositories)
        )

    @mcp.tool(annotations=write)
    @public_errors
    async def register_task(
        project_id: UUID,
        external_id: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        plane_item_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Register external task ID; plane_item_id is a deprecated compatibility alias."""
        if external_id is not None and plane_item_id is not None:
            raise ServiceError(422, "Specify external_id only, not both aliases")
        item_id = external_id if external_id is not None else str(plane_item_id or "")
        if not item_id:
            raise ServiceError(422, "External task id is required")
        return await service.register_task(project_id, item_id)

    @mcp.tool(annotations=read)
    @public_errors
    async def get_task_context(
        task_id: UUID,
        repo: str,
        ref: str,
        refresh: bool = True,
    ) -> dict[str, Any]:
        """Get tracker requirements, freshness, exact-ref docs and recent work reports."""
        return await service.context(task_id, repo, ref, refresh)

    @mcp.tool(annotations=read)
    @public_errors
    async def read_project_document(document_id: UUID) -> dict[str, Any]:
        """Read the full exact-revision document referenced by get_task_context or search."""
        return await service.read_document(document_id)

    @mcp.tool(annotations=read)
    @public_errors
    async def get_task_history(
        task_id: UUID,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        """Read immutable reports with keyset pagination and recent status events."""
        return await service.history(task_id, cursor, limit)

    @mcp.tool(annotations=read)
    @public_errors
    async def find_related_context(
        project_id: UUID,
        query: str,
        repo: str | None = None,
        ref: str | None = None,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> dict[str, Any]:
        """Search project documents and reports. Specify ref to restrict revision."""
        return await service.search(project_id, query, repo, ref, limit)

    @mcp.tool(annotations=write)
    @public_errors
    async def start_work_session(task_id: UUID, session: SessionCreate) -> dict[str, Any]:
        """Start a developer-owned agent session linked to a repository and branch."""
        return await service.start_session(task_id, session)

    @mcp.tool(annotations=write)
    @public_errors
    async def submit_work_report(task_id: UUID, report: ReportCreate) -> dict[str, Any]:
        """Append a work report. Reuse idempotency_key only for an identical retry."""
        return await service.submit_report(task_id, report)

    @mcp.tool(annotations=write)
    @public_errors
    async def transition_task(task_id: UUID, transition: Transition) -> dict[str, Any]:
        """Admin-only tracker transition with expected state and project allowlist."""
        return await service.transition(task_id, transition)

    return mcp
