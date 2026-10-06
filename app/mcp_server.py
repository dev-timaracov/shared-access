from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from app.errors import ServiceError
from app.schemas import ReportCreate, SessionCreate, Transition


def create_mcp(service, settings):
    mcp = FastMCP(
        "Project Context",
        instructions=(
            "List projects, register the Plane task, then get_task_context before editing. "
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
                return await function(*args, **kwargs)
            except ServiceError as exc:
                raise ValueError(f"{exc.status}: {exc.message}") from None

        return wrapped

    @mcp.tool(annotations=read)
    @public_errors
    async def list_projects() -> dict[str, Any]:
        """List accessible projects and registered repositories."""
        return {"projects": await service.list_projects()}

    @mcp.tool(annotations=write)
    @public_errors
    async def register_task(project_id: UUID, plane_item_id: UUID) -> dict[str, Any]:
        """Register a Plane work-item UUID; returns the service task UUID. Idempotent."""
        return await service.register_task(project_id, plane_item_id)

    @mcp.tool(annotations=read)
    @public_errors
    async def get_task_context(
        task_id: UUID,
        repo: str,
        ref: str,
        refresh: bool = True,
    ) -> dict[str, Any]:
        """Get Plane requirements, freshness, exact-ref docs and recent agent work reports."""
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
        """Admin-only explicit Plane transition with expected state and project allowlist."""
        return await service.transition(task_id, transition)

    return mcp
