from app.trackers.base import (
    TaskContext,
    TaskPage,
    TaskSnapshot,
    TaskTracker,
    TrackerProject,
    TrackerReport,
)


class MemoryTracker(TaskTracker):
    provider = "memory"

    def __init__(self):
        self.state = "open"
        self.published: list[TrackerReport] = []

    async def get_task(self, project: TrackerProject, external_id: str) -> TaskSnapshot:
        return TaskSnapshot(id=external_id, name="Tracker-independent task", state_id=self.state)

    async def list_tasks(self, project, cursor=None, limit=20):
        return TaskPage([await self.get_task(project, "TEAM-123")])

    async def get_task_context(self, project: TrackerProject, external_id: str) -> TaskContext:
        return TaskContext(await self.get_task(project, external_id), ("Test adapter",))

    async def transition_task(
        self,
        project: TrackerProject,
        external_id: str,
        state_id: str,
    ) -> TaskSnapshot:
        self.state = state_id
        return await self.get_task(project, external_id)

    async def publish_report(
        self,
        project: TrackerProject,
        external_id: str,
        report: TrackerReport,
    ) -> None:
        if not any(existing.id == report.id for existing in self.published):
            self.published.append(report)
