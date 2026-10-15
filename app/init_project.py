"""Create missing specifications and agent skills in a selected project checkout."""

import argparse
import os
import subprocess
from pathlib import Path

import httpx

from app.specifications import specification_templates


def git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(checkout), *args], text=True).strip()


def checkout_revision(project_dir: Path, repo: str, ref: str) -> tuple[Path, str]:
    root = project_dir.resolve(strict=True)
    if not root.is_dir() or Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("--project-dir must be the target Git checkout root")

    # Match the registered identifier to a remote; tolerate the conventional .git suffix.
    def normalized(value: str) -> str:
        return value.rstrip("/").removesuffix(".git")

    remotes = git(root, "remote").splitlines()
    urls = [git(root, "remote", "get-url", name) for name in remotes]
    if normalized(repo) not in {normalized(url) for url in urls}:
        raise ValueError("Registered repository does not match a remote in --project-dir")
    sha = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return root, sha


def write_specifications(root: Path, files: list[dict]) -> list[dict]:
    root = root.resolve(strict=True)
    expected = set(specification_templates(""))
    if len(files) != len(expected) or {item["path"] for item in files} != expected:
        raise ValueError("Unexpected specification paths returned by server")
    targets = []
    for item in files:
        target = root / item["path"]
        if not target.resolve().is_relative_to(root) or target.is_symlink():
            raise ValueError("Specification path escapes checkout or is a symlink")
        if not isinstance(item["content"], str) or not item["content"]:
            raise ValueError("Invalid specification content returned by server")
        targets.append((target, item))
    results = []
    for target, item in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8", newline="\n") as output:
                output.write(item["content"])
            created = True
        except FileExistsError:
            created = False
        results.append({"path": str(target), "created": created})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--repo", required=True, help="Registered repository URL matching a Git remote"
    )
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()
    root, sha = checkout_revision(args.project_dir, args.repo, args.ref)
    token = os.environ.get("CONTEXT_API_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=30, headers=headers) as client:
        response = client.post(
            f"{args.api_url.rstrip('/')}/api/projects/{args.project_id}/init",
            json={"repo": args.repo, "ref": sha},
        )
        response.raise_for_status()
        result = response.json()
    if (
        result["project_id"] != args.project_id
        or result["repo"] != args.repo
        or result["ref"] != sha
    ):
        raise ValueError("Initialization response does not match the selected project/revision")
    for item in write_specifications(root, result["files"]):
        print(f"{'Created' if item['created'] else 'Preserved'} {item['path']}")
    print("Fill project drafts from source; keep common standards and .agents/skills unchanged.")


if __name__ == "__main__":
    main()
