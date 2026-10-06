import asyncio
import html
import logging
from datetime import timedelta

import httpx
from sqlalchemy import and_, or_, select

from app.config import Settings
from app.db import create_database
from app.models import Outbox, Project, Report, Task, now
from app.plane import PlaneClient

logger = logging.getLogger(__name__)


async def process_one(sessions, plane):
    """Claim a durable job. A lease recovers work after a crashed worker."""
    async with sessions() as db:
        async with db.begin():
            job = await db.scalar(
                select(Outbox)
                .where(
                    Outbox.available_at <= now(),
                    or_(
                        Outbox.status == "pending",
                        and_(Outbox.status == "processing", Outbox.available_at <= now()),
                    ),
                )
                .order_by(Outbox.available_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return False
            job.status = "processing"
            job.attempts += 1
            attempt = job.attempts
            job.available_at = now() + timedelta(minutes=5)
            job_id = job.id
            report = await db.get(Report, job.report_id)
            task = await db.get(Task, report.task_id)
            project = await db.get(Project, task.project_id)
    payload = report.payload
    body = "\n".join(
        [
            f"Agent report {report.id}; developer: {report.developer_id}",
            f"Outcome: {payload['outcome']}",
            payload["summary"],
            "Decisions: " + "; ".join(payload["decisions"]),
            "Blockers: " + "; ".join(payload["blockers"]),
            "Next steps: " + "; ".join(payload["next_steps"]),
            f"Head SHA: {payload['head_sha']}; PR: {payload['pr_url']}",
            "Checks (agent-reported): " + str(payload["checks"]),
        ]
    )
    try:
        async with asyncio.timeout(60):
            await plane.publish_report(project, task, report, f"<pre>{html.escape(body)}</pre>")
        status, error = "sent", None
    except Exception as exc:
        # Do not persist upstream bodies, URLs or credentials in retry errors.
        status, error = ("dead" if attempt >= 10 else "pending"), type(exc).__name__
        logger.warning("Report synchronization failed: job=%s error=%s", job_id, error)
    async with sessions() as db:
        async with db.begin():
            job = await db.get(Outbox, job_id, with_for_update=True)
            if job.status == "processing" and job.attempts == attempt:
                job.status = status
                job.last_error = error
                job.available_at = now() + timedelta(seconds=min(3600, 2**attempt * 5))
    return True


async def main():
    settings = Settings()
    engine, sessions = create_database(settings.database_url)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            plane = PlaneClient(settings, http)
            while True:
                try:
                    worked = await process_one(sessions, plane)
                except Exception:
                    logger.exception("Worker iteration failed")
                    worked = False
                if not worked:
                    await asyncio.sleep(5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
