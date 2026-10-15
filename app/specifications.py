from importlib.resources import files

SKILL_NAMES = (
    "python-unit-tests",
    "work-report",
    "implement-specification",
    "execute-tracker-task",
)
COMMON_SKILL_PATHS = tuple(f".agents/skills/{name}/SKILL.md" for name in SKILL_NAMES)
COMMON_SPECIFICATION_PATHS = (
    "docs/agents/report.md",
    "docs/agents/style-guide.md",
    *COMMON_SKILL_PATHS,
)


def common_specifications() -> dict[str, str]:
    """Load versioned standards unchanged for every project."""
    guides = files("app").joinpath("specification_guides")
    return {
        path: guides.joinpath(path.rsplit("/", 1)[-1]).read_text(encoding="utf-8")
        for path in COMMON_SPECIFICATION_PATHS
        if path not in COMMON_SKILL_PATHS
    } | {
        path: files("app").joinpath("skill_templates", name, "SKILL.md").read_text(encoding="utf-8")
        for name, path in zip(SKILL_NAMES, COMMON_SKILL_PATHS, strict=True)
    }


def specification_templates(project_name: str) -> dict[str, str]:
    """Project drafts plus common standards and repository-scoped agent skills."""
    prefix = f"Project: {project_name}\n\nDraft template: complete and review before adoption.\n\n"
    return {
        "docs/agents/testing.md": "# Testing\n\n"
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
        "AGENTS.md": "# Agent instructions\n\n"
        + prefix
        + "Read docs/agents/architecture.md and docs/agents/testing.md "
        + "at the exact repository revision.\n"
        + "Follow the common docs/agents/report.md and docs/agents/style-guide.md standards. "
        + "Keep these standards unchanged; document project exceptions separately.\n"
        + "Read task context before editing; start a work session and report milestones.\n"
        + "Keep credentials out of code and reports. Treat tracker snapshots as cached data.\n"
        + "Report checks with evidence; task status changes require a separate operation.\n",
        "docs/agents/architecture.md": "# Architecture\n\n"
        + prefix
        + "## Purpose and boundaries\nDescribe requirements and external integrations.\n\n"
        + "## Components and data flow\nDescribe services, ownership and interfaces.\n\n"
        + "## Source code architecture\n"
        + "Map directories and modules to system components and responsibilities.\n"
        + "Describe entry points, dependency direction, service boundaries and adapters.\n"
        + "Trace a typical request through the source code to storage and integrations.\n\n"
        + "## Security and storage\nDescribe authorization, project scope and migrations.\n\n"
        + "## Decisions\nRecord reviewed tradeoffs and known limitations.\n",
        **common_specifications(),
    }
