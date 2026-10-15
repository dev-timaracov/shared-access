import subprocess

import httpx
import pytest

from app.init_project import checkout_revision, main, write_specifications
from app.specifications import COMMON_SKILL_PATHS, specification_templates


def files():
    return [
        {"path": path, "content": content}
        for path, content in specification_templates("Demo").items()
    ]


def test_write_to_selected_checkout_preserves_existing_files(tmp_path, monkeypatch):
    server = tmp_path / "shared-access"
    project = tmp_path / "target-project"
    server.mkdir()
    project.mkdir()
    monkeypatch.chdir(server)
    (project / "AGENTS.md").write_text("custom", encoding="utf-8")
    existing_skill = project / COMMON_SKILL_PATHS[0]
    existing_skill.parent.mkdir(parents=True)
    existing_skill.write_text("custom skill", encoding="utf-8")
    existing_guide = project / "docs/agents/frontend-style-guide.md"
    existing_guide.parent.mkdir(parents=True)
    existing_guide.write_text("custom frontend guide", encoding="utf-8")
    result = write_specifications(project, files())
    assert sum(item["created"] for item in result) == 7
    assert (project / "AGENTS.md").read_text() == "custom"
    assert existing_skill.read_text() == "custom skill"
    assert existing_guide.read_text() == "custom frontend guide"
    for path in COMMON_SKILL_PATHS[1:]:
        assert (project / path).read_text(encoding="utf-8") == specification_templates("Demo")[path]
    assert (project / "docs/agents/testing.md").read_text().startswith("# Testing")
    assert list(server.iterdir()) == []
    assert all(not item["created"] for item in write_specifications(project, files()))


def test_reject_unexpected_paths_before_writing(tmp_path):
    payload = files()
    payload[-1]["path"] = "../report.md"
    with pytest.raises(ValueError, match="Unexpected specification paths"):
        write_specifications(tmp_path, payload)
    assert list(tmp_path.iterdir()) == []


def test_reject_incomplete_scaffold_before_writing(tmp_path):
    payload = [item for item in files() if item["path"] != COMMON_SKILL_PATHS[0]]
    with pytest.raises(ValueError, match="Unexpected specification paths"):
        write_specifications(tmp_path, payload)
    assert list(tmp_path.iterdir()) == []


def test_cli_selects_project_and_resolves_its_revision(tmp_path, monkeypatch):
    project = tmp_path / "target"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )
    repo = "https://example.org/team/project"
    subprocess.run(
        ["git", "-C", str(project), "remote", "add", "origin", repo + ".git"], check=True
    )
    root, sha = checkout_revision(project, repo, "HEAD")
    assert root == project and len(sha) == 40
    with pytest.raises(ValueError, match="does not match"):
        checkout_revision(project, "https://example.org/other", "HEAD")
    with pytest.raises(subprocess.CalledProcessError):
        checkout_revision(project, repo, "missing-ref")
    (project / "subdir").mkdir()
    with pytest.raises(ValueError, match="checkout root"):
        checkout_revision(project / "subdir", repo, "HEAD")

    def handler(request):
        import json

        assert request.url.path == "/api/projects/project-id/init"
        assert json.loads(request.content) == {"repo": repo, "ref": sha}
        return httpx.Response(
            200, json={"project_id": "project-id", "repo": repo, "ref": sha, "files": files()}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.init_project.httpx.Client", lambda **kwargs: client)
    monkeypatch.setattr(
        "sys.argv",
        ["init", "--project-dir", str(project), "--project-id", "project-id", "--repo", repo],
    )
    monkeypatch.chdir(tmp_path)
    main()
    assert (project / "AGENTS.md").is_file()
    assert (project / "docs/agents/frontend-style-guide.md").read_text(
        encoding="utf-8"
    ) == specification_templates("Demo")["docs/agents/frontend-style-guide.md"]
    assert all((project / path).is_file() for path in COMMON_SKILL_PATHS)
    assert not (tmp_path / "AGENTS.md").exists()
