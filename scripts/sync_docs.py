"""Upload tracked Markdown at an exact Git commit. Run from a project's checkout."""

import argparse
import os
import subprocess

import httpx


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--repo", required=True, help="Registered repository identifier")
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    token = os.environ["CONTEXT_API_TOKEN"]
    # Resolve once; every document is fetched from the same immutable tree.
    sha = git("rev-parse", "--verify", f"{args.ref}^{{commit}}").decode().strip()
    entries = git("ls-tree", "-r", "-z", sha, "--", "AGENTS.md", "docs/agents").split(b"\0")
    count = 0
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"}) as client:
        for entry in entries:
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, _ = metadata.split()
            path = raw_path.decode("utf-8")
            if kind != b"blob" or mode == b"120000" or not path.endswith(".md"):
                continue
            content = git("show", f"{sha}:{path}").decode("utf-8")
            response = client.put(
                f"{args.api_url.rstrip('/')}/api/projects/{args.project_id}/documents",
                json={"repo": args.repo, "ref": sha, "path": path, "content": content},
            )
            response.raise_for_status()
            count += 1
    print(f"Uploaded {count} documents at {sha}")


if __name__ == "__main__":
    main()
