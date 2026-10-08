import base64
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import and_, func, literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.auth import current_identity
from app.errors import ServiceError
from app.models import (
    Document,
    GitLink,
    Outbox,
    Project,
    Report,
    Task,
    TaskEvent,
    WorkSession,
    now,
)
from app.schemas import (
    DocumentPut,
    ProjectCreate,
    ProjectInit,
    ReportCreate,
    RepositoriesAdd,
    SessionCreate,
    Transition,
)
from app.trackers.base import TaskSnapshot, TaskTracker, TrackerProject


def timestamp(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()


def report_view(report):
    return {
        "id": report.id,
        "task_id": report.task_id,
        "session_id": report.session_id,
        "developer_id": report.developer_id,
        "created_at": timestamp(report.created_at),
        "evidence_type": "agent_report",
        **report.payload,
    }


class ContextService:
    def __init__(self, settings, sessions, tracker: TaskTracker):
        self.settings = settings
        self.sessions = sessions
        self.tracker = tracker

    def tracker_project(self, project) -> TrackerProject:
        if project.tracker_provider != self.tracker.provider:
            raise ServiceError(503, "Project tracker does not match the configured adapter")
        if not project.tracker_workspace or not project.tracker_project_id:
            raise ServiceError(503, "Task tracker project mapping is not configured")
        return TrackerProject(project.tracker_workspace, project.tracker_project_id)

    @staticmethod
    def require_write():
        if current_identity().role not in {"writer", "admin"}:
            raise ServiceError(403, "Write access required")

    @staticmethod
    def require_admin():
        if current_identity().role != "admin":
            raise ServiceError(403, "Administrator access required")

    async def project(self, db, project_id):
        project = await db.get(Project, str(project_id))
        actor = current_identity()
        if project is None or not (
            project.slug in actor.projects or (actor.role == "admin" and "*" in actor.projects)
        ):
            raise ServiceError(404, "Project not found")
        return project

    async def task(self, db, task_id):
        task = await db.get(Task, str(task_id))
        if task is None:
            raise ServiceError(404, "Task not found")
        project = await self.project(db, task.project_id)
        return task, project

    @staticmethod
    def check_repo(project, repo):
        if repo not in project.repositories:
            raise ServiceError(422, "Repository is not registered for this project")

    async def create_project(self, data: ProjectCreate):
        self.require_admin()
        if "*" not in current_identity().projects and data.slug not in current_identity().projects:
            raise ServiceError(403, "Project is outside your scope")
        values = data.model_dump(mode="json")
        if data.tracker_provider != self.tracker.provider:
            raise ServiceError(422, "Project tracker does not match the configured adapter")
        if data.tracker_project_id:
            self.tracker.validate_project(
                TrackerProject(data.tracker_workspace, data.tracker_project_id)
            )
        async with self.sessions() as db:
            project = Project(**values)
            db.add(project)
            try:
                await db.commit()
            except IntegrityError:
                raise ServiceError(409, "Project slug already exists") from None
            return {"id": project.id, **values}

    async def list_projects(self):
        async with self.sessions() as db:
            actor = current_identity()
            query = select(Project).order_by(Project.slug)
            if not (actor.role == "admin" and "*" in actor.projects):
                query = query.where(Project.slug.in_(actor.projects))
            projects = (await db.scalars(query)).all()
            return [
                {"id": p.id, "slug": p.slug, "name": p.name, "repositories": p.repositories}
                for p in projects
            ]

    async def add_project_repositories(self, project_id, data: RepositoriesAdd):
        self.require_admin()
        async with self.sessions() as db:
            project = await self.project(db, project_id)
            repositories = list(dict.fromkeys([*project.repositories, *data.repositories]))
            if len(repositories) > 30:
                raise ServiceError(422, "A project can have at most 30 repositories")
            result = await db.execute(
                update(Project)
                .where(Project.id == project.id, Project.repositories == project.repositories)
                .values(repositories=repositories)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise ServiceError(409, "Concurrent repository update; retry")
            await db.commit()
            return {"id": project.id, "repositories": repositories}

    async def list_tracker_tasks(self, project_id, cursor=None, limit=20):
        if not 1 <= limit <= 100 or (cursor is not None and (not cursor or len(cursor) > 2000)):
            raise ServiceError(422, "Limit must be 1..100; cursor must be 1..2000 characters")
        async with self.sessions() as db:
            project = await self.project(db, project_id)
            page = await self.tracker.list_tasks(self.tracker_project(project), cursor, limit)
            return {
                "project_id": project.id,
                "tracker_provider": project.tracker_provider,
                "tasks": [task.model_dump(mode="json") for task in page.tasks],
                "next_cursor": page.next_cursor,
                "freshness": "live",
                "fetched_at": timestamp(now()),
            }

    async def register_task(self, project_id, external_id):
        self.require_write()
        async with self.sessions() as db:
            project = await self.project(db, project_id)
            self.tracker_project(project)
            self.tracker.validate_external_id(external_id)
            query = select(Task).where(
                Task.project_id == str(project_id), Task.external_id == str(external_id)
            )
            task = await db.scalar(query)
            if task is None:
                task = Task(project_id=str(project_id), external_id=str(external_id))
                db.add(task)
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    task = await db.scalar(query)
                    if task is None:
                        raise ServiceError(409, "Task registration conflicted") from None
            return {
                "id": task.id,
                "project_id": task.project_id,
                "external_id": task.external_id,
                "tracker_provider": project.tracker_provider,
            }

    async def init_project(self, project_id, data: ProjectInit):
        self.require_admin()
        from app.specifications import specification_templates

        async with self.sessions() as db:
            project = await self.project(db, project_id)
            self.check_repo(project, data.repo)
            documents = []
            for path, content in specification_templates(project.name).items():
                doc = await db.scalar(
                    select(Document).where(
                        Document.project_id == project.id,
                        Document.repo == data.repo,
                        Document.ref == data.ref,
                        Document.path == path,
                    )
                )
                created = doc is None
                if created:
                    doc = Document(
                        project_id=project.id,
                        repo=data.repo,
                        ref=data.ref,
                        path=path,
                        content=content,
                    )
                    db.add(doc)
                    try:
                        await db.flush()
                    except IntegrityError:
                        raise ServiceError(409, "Concurrent initialization; retry") from None
                documents.append({"id": doc.id, "path": path, "created": created})
            try:
                await db.commit()
            except IntegrityError:
                raise ServiceError(409, "Concurrent initialization; retry") from None
            return {
                "project_id": project.id,
                "repo": data.repo,
                "ref": data.ref,
                "documents": documents,
                "template": True,
            }

    async def sync_project(self, project_id):
        self.require_write()
        async with self.sessions() as db:
            project = await self.project(db, project_id)
            mapping = self.tracker_project(project)
            cursor = None
            seen = set()
            snapshots = {}
            while True:
                page = await self.tracker.list_tasks(mapping, cursor, 100)
                for snapshot in page.tasks:
                    if not snapshot.id or len(snapshot.id) > 200:
                        raise ServiceError(502, "Tracker returned an invalid task id")
                    self.tracker.validate_external_id(snapshot.id)
                    snapshots[snapshot.id] = snapshot
                if page.next_cursor is None:
                    break
                if page.next_cursor in seen:
                    raise ServiceError(502, "Tracker pagination repeated a cursor")
                seen.add(page.next_cursor)
                cursor = page.next_cursor
            fetched_at = now()
            created = 0
            tasks = []
            existing = {
                task.external_id: task
                for task in (
                    await db.scalars(select(Task).where(Task.project_id == project.id))
                ).all()
            }
            for external_id, snapshot in snapshots.items():
                task = existing.get(external_id)
                if task is None:
                    task = Task(project_id=project.id, external_id=external_id)
                    db.add(task)
                    created += 1
                task.snapshot = snapshot.model_dump(mode="json")
                task.fetched_at = fetched_at
                tasks.append(task)
            try:
                await db.commit()
            except IntegrityError:
                raise ServiceError(409, "Concurrent task sync; retry") from None
            return {
                "project_id": project.id,
                "tracker_provider": project.tracker_provider,
                "created": created,
                "updated": len(tasks) - created,
                "freshness": "live",
                "fetched_at": timestamp(fetched_at),
                "tasks": [{"id": t.id, "external_id": t.external_id} for t in tasks],
            }

    async def start_session(self, task_id, data: SessionCreate):
        self.require_write()
        async with self.sessions() as db:
            task, project = await self.task(db, task_id)
            self.check_repo(project, data.repo)
            session = WorkSession(
                task_id=task.id,
                developer_id=current_identity().developer_id,
                **data.model_dump(mode="json"),
            )
            db.add(session)
            await db.commit()
            return {
                "id": session.id,
                "task_id": task.id,
                "developer_id": session.developer_id,
                **data.model_dump(mode="json"),
            }

    async def submit_report(self, task_id, data: ReportCreate):
        self.require_write()
        payload = data.model_dump(mode="json", exclude={"idempotency_key", "session_id"})
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        async with self.sessions() as db:
            task, project = await self.task(db, task_id)
            session = await db.get(WorkSession, str(data.session_id))
            actor = current_identity()
            if session is None or session.task_id != task.id:
                raise ServiceError(404, "Session not found for this task")
            if session.developer_id != actor.developer_id:
                raise ServiceError(403, "Cannot submit a report for another developer's session")
            lookup = select(Report).where(
                Report.session_id == session.id, Report.idempotency_key == data.idempotency_key
            )
            existing = await db.scalar(lookup)
            if existing:
                return self.replay(existing, digest)
            report = Report(
                task_id=task.id,
                session_id=session.id,
                developer_id=actor.developer_id,
                idempotency_key=data.idempotency_key,
                payload_hash=digest,
                payload=payload,
                search_text="\n".join(
                    [
                        data.summary,
                        *data.decisions,
                        *data.blockers,
                        *data.next_steps,
                    ]
                ),
            )
            db.add(report)
            try:
                await db.flush()
                links = {("branch", session.branch)}
                links.update(("commit", sha) for sha in data.commits)
                if data.head_sha:
                    links.add(("commit", data.head_sha))
                if data.pr_url:
                    links.add(("pr", str(data.pr_url)))
                for kind, value in links:
                    query = select(GitLink.id).where(
                        GitLink.task_id == task.id,
                        GitLink.repo == session.repo,
                        GitLink.kind == kind,
                        GitLink.value == value,
                    )
                    if not await db.scalar(query):
                        # Savepoint handles two reports linking the same commit concurrently.
                        try:
                            async with db.begin_nested():
                                db.add(
                                    GitLink(
                                        task_id=task.id, repo=session.repo, kind=kind, value=value
                                    )
                                )
                                await db.flush()
                        except IntegrityError:
                            pass
                if self.settings.tracker_sync_reports and project.tracker_project_id:
                    db.add(Outbox(report_id=report.id))
                await db.commit()
            except IntegrityError:
                await db.rollback()
                existing = await db.scalar(lookup)
                if existing is None:
                    raise ServiceError(409, "Concurrent report write conflicted; retry") from None
                return self.replay(existing, digest)
            return {
                "report": report_view(report),
                "replayed": False,
                "tracker_provider": project.tracker_provider,
                "tracker_sync": "queued"
                if self.settings.tracker_sync_reports and project.tracker_project_id
                else "disabled",
            }

    @staticmethod
    def replay(existing, digest):
        if existing.payload_hash != digest:
            raise ServiceError(409, "Idempotency key already used for a different report")
        return {"report": report_view(existing), "replayed": True}

    async def history(self, task_id, cursor=None, limit=20):
        if not 1 <= limit <= 50:
            raise ServiceError(422, "Limit must be between 1 and 50")
        async with self.sessions() as db:
            task, _ = await self.task(db, task_id)
            query = select(Report).where(Report.task_id == task.id)
            if cursor:
                try:
                    decoded = json.loads(base64.urlsafe_b64decode(cursor))
                    if decoded["task"] != task.id:
                        raise ValueError()
                    time = datetime.fromisoformat(decoded["time"])
                    report_id = decoded["id"]
                except (ValueError, KeyError, TypeError):
                    raise ServiceError(422, "Invalid history cursor") from None
                query = query.where(
                    or_(
                        Report.created_at < time,
                        and_(Report.created_at == time, Report.id < report_id),
                    )
                )
            reports = (
                await db.scalars(
                    query.order_by(Report.created_at.desc(), Report.id.desc()).limit(limit + 1)
                )
            ).all()
            items = reports[:limit]
            next_cursor = None
            if len(reports) > limit:
                last = items[-1]
                next_cursor = base64.urlsafe_b64encode(
                    json.dumps(
                        {
                            "task": task.id,
                            "time": timestamp(last.created_at),
                            "id": last.id,
                        }
                    ).encode()
                ).decode()
            events = (
                await db.scalars(
                    select(TaskEvent)
                    .where(TaskEvent.task_id == task.id)
                    .order_by(TaskEvent.created_at.desc(), TaskEvent.id.desc())
                    .limit(20)
                )
            ).all()
            return {
                "reports": [report_view(r) for r in items],
                "next_cursor": next_cursor,
                "recent_events": [
                    {
                        "id": e.id,
                        "actor": e.actor,
                        "payload": e.payload,
                        "created_at": timestamp(e.created_at),
                    }
                    for e in events
                ],
            }

    async def context(self, task_id, repo, ref, refresh=True):
        warnings = []
        async with self.sessions() as db:
            task, project = await self.task(db, task_id)
            self.check_repo(project, repo)
            live = False
            if refresh:
                try:
                    details = await self.tracker.get_task_context(
                        self.tracker_project(project), task.external_id
                    )
                    warnings.extend(details.warnings)
                    snapshot = details.snapshot.model_dump(mode="json")
                    state = details.snapshot.state_id
                    if (
                        task.snapshot
                        and TaskSnapshot.model_validate(task.snapshot).state_id != state
                    ):
                        db.add(
                            TaskEvent(
                                task_id=task.id,
                                actor=project.tracker_provider,
                                payload={
                                    "type": "observed_state_change",
                                    "state_id": state,
                                    "note": (
                                        "Observed on refresh; intermediate changes may be missing"
                                    ),
                                },
                            )
                        )
                    task.snapshot = snapshot
                    task.fetched_at = now()
                    await db.commit()
                    live = True
                except ServiceError as exc:
                    warnings.append(exc.message)
            if not live:
                warnings.append(
                    "Tracker snapshot is cached or unavailable; do not infer current state"
                )
            docs = (
                await db.scalars(
                    select(Document)
                    .where(
                        Document.project_id == project.id,
                        Document.repo == repo,
                        Document.ref == ref,
                    )
                    .order_by(Document.path)
                    .limit(10)
                )
            ).all()
            if not docs:
                warnings.append("No documents for this exact repo/ref; read local AGENTS.md")
            sessions = (
                await db.scalars(
                    select(WorkSession)
                    .where(WorkSession.task_id == task.id)
                    .order_by(WorkSession.created_at.desc(), WorkSession.id.desc())
                    .limit(10)
                )
            ).all()
            reports = (
                await db.scalars(
                    select(Report)
                    .where(Report.task_id == task.id)
                    .order_by(Report.created_at.desc(), Report.id.desc())
                    .limit(5)
                )
            ).all()
            links = (
                await db.scalars(
                    select(GitLink)
                    .where(GitLink.task_id == task.id)
                    .order_by(GitLink.id)
                    .limit(100)
                )
            ).all()
            return {
                "task_id": task.id,
                "project": {"id": project.id, "slug": project.slug},
                "repo": repo,
                "ref": ref,
                "tracker": {
                    "provider": project.tracker_provider,
                    "item_id": task.external_id,
                    "snapshot": TaskSnapshot.model_validate(task.snapshot).model_dump(mode="json")
                    if task.snapshot
                    else {},
                    "fetched_at": timestamp(task.fetched_at),
                    "freshness": "live" if live else "cached" if task.fetched_at else "unavailable",
                },
                "documents": [
                    {
                        "id": d.id,
                        "path": d.path,
                        "excerpt": d.content[:2000],
                        "truncated": len(d.content) > 2000,
                        "source_url": d.source_url,
                        "updated_at": timestamp(d.updated_at),
                    }
                    for d in docs
                ],
                "recent_reports": [
                    {
                        "id": r.id,
                        "session_id": r.session_id,
                        "developer_id": r.developer_id,
                        "created_at": timestamp(r.created_at),
                        "outcome": r.payload["outcome"],
                        "summary": r.payload["summary"][:2000],
                        "details": "get_task_history",
                    }
                    for r in reports
                ],
                "recent_sessions": [
                    {
                        "id": s.id,
                        "developer_id": s.developer_id,
                        "agent_client": s.agent_client,
                        "repo": s.repo,
                        "branch": s.branch,
                        "base_sha": s.base_sha,
                        "created_at": timestamp(s.created_at),
                    }
                    for s in sessions
                ],
                "git_links": [
                    {"repo": link.repo, "kind": link.kind, "value": link.value, "verified": False}
                    for link in links
                ],
                "warnings": warnings
                + [
                    "Git links and check results are agent-reported; CI is not queried in this MVP",
                ],
            }

    async def put_document(self, project_id, data: DocumentPut):
        self.require_admin()
        async with self.sessions() as db:
            project = await self.project(db, project_id)
            self.check_repo(project, data.repo)
            doc = await db.scalar(
                select(Document).where(
                    Document.project_id == project.id,
                    Document.repo == data.repo,
                    Document.ref == data.ref,
                    Document.path == data.path,
                )
            )
            values = data.model_dump(mode="json")
            if doc is None:
                doc = Document(project_id=project.id, **values)
                db.add(doc)
            else:
                for key, value in values.items():
                    setattr(doc, key, value)
                doc.updated_at = now()
            try:
                await db.commit()
            except IntegrityError:
                raise ServiceError(409, "Concurrent document update; retry") from None
            return {"id": doc.id, "repo": doc.repo, "ref": doc.ref, "path": doc.path}

    async def read_document(self, document_id):
        async with self.sessions() as db:
            doc = await db.get(Document, str(document_id))
            if doc is None:
                raise ServiceError(404, "Document not found")
            await self.project(db, doc.project_id)
            return {
                "id": doc.id,
                "repo": doc.repo,
                "ref": doc.ref,
                "path": doc.path,
                "content": doc.content,
                "source_url": doc.source_url,
                "updated_at": timestamp(doc.updated_at),
            }

    async def search(self, project_id, query, repo=None, ref=None, limit=10):
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 30:
            raise ServiceError(422, "Query must be 1..500 characters; limit 1..30")
        async with self.sessions() as db:
            project = await self.project(db, project_id)
            if repo:
                self.check_repo(project, repo)
            postgres = db.bind.dialect.name == "postgresql"

            def matches(column):
                if postgres:
                    config = literal_column("'simple'::regconfig")
                    return func.to_tsvector(config, column).op("@@")(
                        func.websearch_to_tsquery(config, query)
                    )
                return column.icontains(query, autoescape=True)

            document_query = select(Document).where(
                Document.project_id == project.id, matches(Document.content)
            )
            report_query = (
                select(Report)
                .join(Task, Report.task_id == Task.id)
                .join(WorkSession, Report.session_id == WorkSession.id)
                .where(Task.project_id == project.id, matches(Report.search_text))
            )
            if repo:
                document_query = document_query.where(Document.repo == repo)
                report_query = report_query.where(WorkSession.repo == repo)
            if ref:
                document_query = document_query.where(Document.ref == ref)
                # A report's exact code revision is its head SHA, not a mutable branch.
                report_query = report_query.where(Report.payload["head_sha"].as_string() == ref)
            docs = (
                await db.scalars(
                    document_query.order_by(Document.updated_at.desc(), Document.id.desc()).limit(
                        limit
                    )
                )
            ).all()
            reports = (
                await db.scalars(
                    report_query.order_by(Report.created_at.desc(), Report.id.desc()).limit(limit)
                )
            ).all()
            return {
                "mode": "postgres_fulltext" if postgres else "substring_test_fallback",
                "documents": [
                    {
                        "id": d.id,
                        "repo": d.repo,
                        "ref": d.ref,
                        "path": d.path,
                        "excerpt": d.content[:2000],
                        "source_url": d.source_url,
                    }
                    for d in docs
                ],
                "reports": [report_view(r) for r in reports],
            }

    async def transition(self, task_id, data: Transition):
        # Status changes are deliberately separate from work reports and admin-only in MVP.
        self.require_admin()
        async with self.sessions() as db:
            task, project = await self.task(db, task_id)
            tracker_project = self.tracker_project(project)
            source = await self.tracker.get_task(tracker_project, task.external_id)
            previous = source.state_id
            target = str(data.target_state_id)
            if previous != str(data.expected_state_id):
                raise ServiceError(409, "Tracker state changed; refresh task context")
            if target not in project.allowed_transitions.get(previous, []):
                raise ServiceError(403, "Transition is not allowed by project configuration")
            result = await self.tracker.transition_task(tracker_project, task.external_id, target)
            if result.state_id != target:
                raise ServiceError(502, "Tracker did not confirm the requested state")
            task.snapshot = result.model_dump(mode="json")
            task.fetched_at = now()
            event = TaskEvent(
                task_id=task.id,
                actor=current_identity().developer_id,
                payload={
                    "type": "state_transition",
                    "from": previous,
                    "to": target,
                    "reason": data.reason,
                },
            )
            db.add(event)
            await db.commit()
            return {"task_id": task.id, "state_id": target, "event_id": event.id}
