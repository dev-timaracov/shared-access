from collections.abc import Callable

import httpx

from app.config import Settings
from app.trackers.base import TaskTracker
from app.trackers.plane import PlaneTaskTracker

TrackerFactory = Callable[[Settings, httpx.AsyncClient], TaskTracker]
FACTORIES: dict[str, TrackerFactory] = {"plane": PlaneTaskTracker}


def create_task_tracker(settings: Settings, http: httpx.AsyncClient) -> TaskTracker:
    factory = FACTORIES.get(settings.task_tracker_provider)
    if factory is None:
        raise ValueError(f"Unsupported task tracker: {settings.task_tracker_provider}")
    return factory(settings, http)
