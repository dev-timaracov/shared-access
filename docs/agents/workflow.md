# Agent workflow

Administrators can call MCP `init(project_id, specification={repo, ref})` to get
project drafts: `AGENTS.md` and `docs/agents/{testing,architecture}.md`, plus
common standards `docs/agents/{report,style-guide}.md`.
`ref` must be a full commit SHA and the repository must be registered.
The response contains `files` with relative `path` and `content`, and
`write_policy=create_missing`. The agent must write these files into the target
project's checkout root, preserving existing files. The server cannot write to
a remote client's filesystem and does not store these drafts in Shared Access.
`common_files` identifies the standards copied unchanged for every project;
their canonical sources are packaged under `app/specification_guides/`.
Project drafts are starter templates, not verified Git blobs or specifications inferred
from source code. Review and commit project-specific content before uploading it
using `scripts/sync_docs.py`; only then is it bound to that resulting commit SHA.
The equivalent REST endpoint is `POST /api/projects/{project_id}/init` with `{repo, ref}`.

For automatic local file creation, run from the Shared Access installation:

```sh
uv run python -m app.init_project --project-dir /absolute/path/to/target-project --project-id PROJECT_UUID --repo REGISTERED_REPOSITORY_URL
```

The directory is required; it must be the target Git checkout root and its remote
must match the registered repository URL (an optional `.git` suffix is tolerated).
`--ref` defaults to that checkout's HEAD and is resolved there, independently of
the process working directory. Use `--api-url` for another server and
`CONTEXT_API_TOKEN` for authenticated servers. Existing files are never overwritten.
Initialization no longer returns stored document IDs or `created` flags; local
creation is reported by the command after writing the files.

Only the project drafts are filled from source; report/style-guide standards
remain identical across projects. Record project exceptions in architecture or
reviewed decisions. Existing files are preserved; updating an older standard
is a separate explicit edit, never a silent overwrite by init.

Project-specific content is the responsibility of the coding agent with access
to the target checkout. Before creating specifications, read existing docs,
inspect the source tree, manifests, entry points, configuration, CI and tests.
Replace placeholders with observed components, data flows, real check commands,
prerequisites and project rules. Record unknowns instead of inventing details;
commands found in CI are not evidence that checks were executed. Preserve existing
specifications and propose needed updates separately. The local command only
creates project scaffolds and copies common standards; it does not analyze code
or call a model. Agent completion and
review are required before committing and uploading the finished specifications.

`testing.md` specifies the testing order, commands and acceptance criteria.
`architecture.md` describes both the system architecture and source code structure.
`report.md` defines the common report fields, identity/ID/date sources and API
mapping, full commit hashes, the resulting `head_sha` and tested `commit_sha`.
`style-guide.md` defines common Python conventions and DDD principles for FastAPI,
including an example from a pinned MosaiHub backend revision.

Writers can call MCP `sync(project_id)` or REST `POST /api/projects/{project_id}/sync`
to import every tracker task page and refresh local snapshots. The response contains
local/external task IDs, created/updated counts and freshness time. Repeated calls
preserve local IDs, sessions and reports; missing upstream tasks are not deleted.
Upstream failures abort the import; concurrent inserts return 409 and can be retried.

1. Read local AGENTS.md and relevant docs at the current checkout revision.
2. Call list_projects and list_tracker_tasks to browse live tracker tasks (follow
   next_cursor), then register_task with the tracker's external_id. Administrators
   can append repositories to an existing project with add_project_repositories.
   For Plane
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
