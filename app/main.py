from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy import text

from app.auth import AuthMiddleware
from app.compat import legacy_response
from app.config import Settings
from app.db import create_database
from app.errors import ServiceError
from app.mcp_server import create_mcp
from app.schemas import (
    DocumentPut,
    ProjectCreate,
    ReportCreate,
    RepositoriesAdd,
    SessionCreate,
    TaskCreate,
    Transition,
)
from app.service import ContextService
from app.trackers.base import TaskTracker
from app.trackers.factory import create_task_tracker


def create_app(
    settings: Settings | None = None,
    http: httpx.AsyncClient | None = None,
    tracker: TaskTracker | None = None,
):
    settings = settings or Settings()
    engine, sessions = create_database(settings.database_url)
    tracker_http = http or httpx.AsyncClient(timeout=20, follow_redirects=False)
    service = ContextService(
        settings, sessions, tracker or create_task_tracker(settings, tracker_http)
    )
    mcp = create_mcp(service, settings)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        # Mounted sub-app lifespan is not executed by FastAPI automatically.
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await engine.dispose()
                if http is None:
                    await tracker_http.aclose()

    app = FastAPI(
        title="Project Context Service",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(HTTPBearer(auto_error=False))],
    )
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.service = service
    app.state.mcp = mcp
    app.add_middleware(
        AuthMiddleware, tokens=settings.auth_tokens, auth_disabled=settings.auth_disabled
    )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        async with sessions() as db:
            try:
                await db.execute(text("SELECT id FROM projects LIMIT 1"))
            except Exception:
                return JSONResponse({"status": "database_unavailable"}, status_code=503)
        return {"status": "ok"}

    @app.get("/api/projects")
    async def list_projects():
        return await service.list_projects()

    @app.post("/api/projects", status_code=201)
    async def create_project(data: ProjectCreate):
        return legacy_response(await service.create_project(data))

    @app.post("/api/projects/{project_id}/repositories")
    async def add_project_repositories(project_id: UUID, data: RepositoriesAdd):
        return await service.add_project_repositories(project_id, data)

    @app.get("/api/projects/{project_id}/tasks")
    async def list_tracker_tasks(
        project_id: UUID,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2000)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        return await service.list_tracker_tasks(project_id, cursor, limit)

    @app.post("/api/projects/{project_id}/tasks", status_code=201)
    async def register_task(project_id: UUID, data: TaskCreate):
        return legacy_response(await service.register_task(project_id, data.external_id))

    @app.put("/api/projects/{project_id}/documents")
    async def put_document(project_id: UUID, data: DocumentPut):
        return await service.put_document(project_id, data)

    @app.get("/api/projects/{project_id}/search")
    async def search(
        project_id: UUID,
        q: Annotated[str, Query(min_length=1, max_length=500)],
        repo: str | None = None,
        ref: str | None = None,
        limit: Annotated[int, Query(ge=1, le=30)] = 10,
    ):
        return await service.search(project_id, q, repo, ref, limit)

    @app.get("/api/documents/{document_id}")
    async def read_document(document_id: UUID):
        return await service.read_document(document_id)

    @app.get("/api/tasks/{task_id}/context")
    async def context(
        task_id: UUID,
        repo: Annotated[str, Query(min_length=1, max_length=300)],
        ref: Annotated[str, Query(min_length=1, max_length=200)],
        refresh: bool = True,
    ):
        return legacy_response(await service.context(task_id, repo, ref, refresh))

    @app.get("/api/tasks/{task_id}/history")
    async def history(
        task_id: UUID,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ):
        return await service.history(task_id, cursor, limit)

    @app.post("/api/tasks/{task_id}/sessions", status_code=201)
    async def start_session(task_id: UUID, data: SessionCreate):
        return await service.start_session(task_id, data)

    @app.post("/api/tasks/{task_id}/reports", status_code=201)
    async def submit_report(task_id: UUID, data: ReportCreate):
        return legacy_response(await service.submit_report(task_id, data))

    @app.post("/api/tasks/{task_id}/transitions")
    async def transition(task_id: UUID, data: Transition):
        return await service.transition(task_id, data)

    app.mount("/mcp", mcp_app)
    return app


# Factory mode keeps imports usable for migrations/tests without configured credentials.
# Run: uvicorn app.main:create_app --factory
