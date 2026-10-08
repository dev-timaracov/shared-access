def specification_templates(project_name: str) -> dict[str, str]:
    """Starter specifications, requiring project-specific review before adoption."""
    prefix = f"Project: {project_name}\n\nDraft template: complete and review before adoption.\n\n"
    return {
        "testing.md": "# Testing\n\n"
        + prefix
        + "## Testing procedure\nRun checks in this order:\n\n"
        + "1. Prepare dependencies, an isolated environment and test data.\n"
        + "2. Run formatting, lint and static checks.\n"
        + "3. Run unit tests for the affected code.\n"
        + "4. Run integration tests, including storage and external adapters.\n"
        + "5. Run end-to-end scenarios and the required regression suite.\n"
        + "6. Record results, failures and skipped checks against the tested commit SHA.\n\n"
        + "## Commands and acceptance criteria\n"
        + "Specify each step's exact commands, prerequisites and pass criteria.\n"
        + "Fix failures and rerun affected checks before reporting completion.\n",
        "agents.md": "# Agent instructions\n\n"
        + prefix
        + "Read architecture.md and testing.md at the exact repository revision.\n"
        + "Read task context before editing; start a work session and report milestones.\n"
        + "Keep credentials out of code and reports. Treat tracker snapshots as cached data.\n"
        + "Report checks with evidence; task status changes require a separate operation.\n",
        "architecture.md": "# Architecture\n\n"
        + prefix
        + "## Purpose and boundaries\nDescribe requirements and external integrations.\n\n"
        + "## Components and data flow\nDescribe services, ownership and interfaces.\n\n"
        + "## Source code architecture\n"
        + "Map directories and modules to system components and responsibilities.\n"
        + "Describe entry points, dependency direction, service boundaries and adapters.\n"
        + "Trace a typical request through the source code to storage and integrations.\n\n"
        + "## Security and storage\nDescribe authorization, project scope and migrations.\n\n"
        + "## Decisions\nRecord reviewed tradeoffs and known limitations.\n",
        "report.md": "# Work report guide\n\n"
        + prefix
        + "Submit append-only work reports through submit_work_report.\n"
        + "## AI agent report structure\n\n"
        + "1. Task and session: task_id, session_id and idempotency_key.\n"
        + "2. Outcome and summary: work performed, resulting behavior and scope.\n"
        + "3. Decisions: implementation choices and their reasons.\n"
        + "4. Code revisions: commits contains the full SHA of every relevant commit; "
        + "head_sha identifies the resulting revision. Include pr_url when available.\n"
        + "5. Checks: command, result, commit_sha of the tested revision and evidence "
        + "or ci_run_url. Explicitly record checks that were not run.\n"
        + "6. Blockers and next_steps: remaining issues and handoff instructions.\n"
        + "7. Uncommitted work: dirty_worktree and artifact_url when applicable.\n\n"
        + "Use full 40- or 64-character hexadecimal commit hashes, not branch names.\n"
        + "If no commits were created, leave commits empty and disclose uncommitted work; "
        + "never invent a commit hash or claim untested changes were tested.\n\n"
        + "Reuse a retry key only for an identical payload.\n"
        + "Git links and agent-reported checks remain unverified until checked against Git/CI.\n"
        + "A report does not change task status.\n",
    }
