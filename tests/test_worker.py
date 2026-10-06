from sqlalchemy import select

from app.errors import ServiceError
from app.models import Outbox, now
from app.worker import process_one
from tests.test_service import report


async def test_outbox_retry_then_delivery(setup_task):
    app, client, _, _, task, session = setup_task
    await client.post(f"/api/tasks/{task['id']}/reports", json=report(session))

    class Plane:
        failed = True
        calls = 0

        async def publish_report(self, project, task, report, html):
            self.calls += 1
            assert "Payment retry" in html
            if self.failed:
                raise ServiceError(502, "timeout")

    plane = Plane()
    assert await process_one(app.state.sessions, plane)
    async with app.state.sessions() as db:
        job = await db.scalar(select(Outbox))
        assert job.status == "pending"
        assert job.attempts == 1
        job.available_at = now()
        await db.commit()
    plane.failed = False
    assert await process_one(app.state.sessions, plane)
    async with app.state.sessions() as db:
        job = await db.scalar(select(Outbox))
        assert job.status == "sent"
        assert job.attempts == 2
    assert not await process_one(app.state.sessions, plane)
