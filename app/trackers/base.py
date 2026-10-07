from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, model_validator


@dataclass(frozen=True)
class TrackerProject:
    workspace: str
    project_id: str


class TaskSnapshot(BaseModel):
    """Provider-neutral, JSON-serializable task data stored in the context database."""

    id: str
    name: str = ""
    state_id: str | None = None
    description_html: str | None = None
    description_stripped: str | None = None
    priority: str | None = None
    identifier: str | None = None
    assignee_ids: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    updated_at: str | None = None
    comments: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def read_legacy_snapshot(cls, value):
        # Existing deployments cached state under "state" before the interface existed.
        if isinstance(value, dict) and "state_id" not in value:
            value = dict(value)
            state = value.get("state")
            value["state_id"] = state.get("id") if isinstance(state, dict) else state
        return value


@dataclass(frozen=True)
class TaskContext:
    snapshot: TaskSnapshot
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackerReport:
    id: str
    content: str


class TaskTracker(ABC):
    """Integration boundary: adapters must not require database models as inputs."""

    provider: str

    def validate_project(self, project: TrackerProject) -> None:
        """Optionally enforce provider-specific project identifiers."""
        return None

    def validate_external_id(self, external_id: str) -> None:
        """Optionally enforce provider-specific task identifiers."""
        return None

    @abstractmethod
    async def get_task(self, project: TrackerProject, external_id: str) -> TaskSnapshot:
        """Read current state. Raise ServiceError on an upstream failure."""

    @abstractmethod
    async def get_task_context(self, project: TrackerProject, external_id: str) -> TaskContext:
        """Read task and supporting details; disclose partially unavailable data."""

    @abstractmethod
    async def transition_task(
        self,
        project: TrackerProject,
        external_id: str,
        state_id: str,
    ) -> TaskSnapshot:
        """Change state and return the confirmed task snapshot."""

    @abstractmethod
    async def publish_report(
        self,
        project: TrackerProject,
        external_id: str,
        report: TrackerReport,
    ) -> None:
        """Publish with best-effort deduplication using the report's stable ID."""
