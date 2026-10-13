from app.specifications import COMMON_SPECIFICATION_PATHS, specification_templates


def test_common_standards_are_identical_across_projects():
    first = specification_templates("Project Alpha")
    second = specification_templates("Project Beta")
    for path in COMMON_SPECIFICATION_PATHS:
        assert first[path] == second[path]
        assert "Project Alpha" not in first[path]
        assert "Draft template" not in first[path]
    assert first["docs/agents/architecture.md"] != second["docs/agents/architecture.md"]
