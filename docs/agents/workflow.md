# Agent workflow

1. Read local AGENTS.md and relevant docs at the current checkout revision.
2. Call list_projects and register_task with the tracker's external_id. For Plane
   this is the work-item UUID; other adapters may use strings such as TEAM-123.
   Store the returned service task UUID; it differs from the external ID.
3. Call get_task_context with repository identifier and current commit SHA.
   Check freshness, recent sessions/reports and warnings. Read full documents
   with read_project_document and more history with get_task_history.
4. Call start_work_session with client, repository, branch and base SHA.
5. Make changes and run relevant checks. Record which commit was tested.
6. Call submit_work_report at a meaningful checkpoint or handoff. Include
   summary, decisions, blockers, next steps, commits, PR and checks. Reuse the
   same idempotency key only when retrying the same report.
7. Do not mark a task done just because implementation finished. An administrator
   may use transition_task after the required review/QA and configured checks.

A session is a work record, not an exclusive lock or a reliable presence signal.
Recent sessions help spot concurrent work; separate worktrees/branches remain
necessary when developers edit the same code. A handoff with uncommitted changes
should include an artifact URL accessible to the next developer.

Important shared decisions should be accepted through review and committed under
docs/agents/decisions. An agent's report alone does not change project rules.
