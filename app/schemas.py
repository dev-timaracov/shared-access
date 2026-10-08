from typing import Annotated, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, model_validator

Short = Annotated[str, Field(min_length=1, max_length=200)]
SHA = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(Input):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    name: Short
    tracker_provider: str = Field(default="plane", min_length=1, max_length=40)
    tracker_workspace: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("tracker_workspace", "plane_workspace"),
    )
    tracker_project_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("tracker_project_id", "plane_project_id"),
    )
    repositories: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=30
    )
    allowed_transitions: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def tracker_pair(self):
        if bool(self.tracker_workspace) != bool(self.tracker_project_id):
            raise ValueError("Tracker workspace and project id must be configured together")
        return self


class RepositoriesAdd(Input):
    repositories: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        min_length=1, max_length=30
    )


class TaskCreate(Input):
    external_id: str = Field(
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("external_id", "plane_item_id"),
    )


class SessionCreate(Input):
    agent_client: str = Field(min_length=1, max_length=80)
    repo: str = Field(min_length=1, max_length=300)
    branch: Short
    base_sha: SHA | None = None


class Check(Input):
    command: str = Field(min_length=1, max_length=1000)
    result: Literal["passed", "failed", "not_run"]
    commit_sha: SHA | None = None
    ci_run_url: HttpUrl | None = None
    evidence: str | None = Field(default=None, max_length=4000)


class ReportCreate(Input):
    session_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    outcome: Literal["progress", "implemented", "blocked", "handoff"]
    summary: str = Field(min_length=1, max_length=12000)
    decisions: list[Annotated[str, Field(max_length=4000)]] = Field(
        default_factory=list, max_length=30
    )
    blockers: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=30
    )
    next_steps: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=30
    )
    head_sha: SHA | None = None
    commits: list[SHA] = Field(default_factory=list, max_length=100)
    pr_url: HttpUrl | None = None
    dirty_worktree: bool = False
    artifact_url: HttpUrl | None = None
    checks: list[Check] = Field(default_factory=list, max_length=30)


class DocumentPut(Input):
    repo: str = Field(min_length=1, max_length=300)
    ref: Short
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100000)
    source_url: HttpUrl | None = None


class Transition(Input):
    expected_state_id: Short
    target_state_id: Short
    reason: str = Field(min_length=1, max_length=2000)
