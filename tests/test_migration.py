import asyncio
import json
import sqlite3
import sys

from app.trackers.base import TaskSnapshot


async def test_existing_plane_mappings_and_history_survive_upgrade(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("AUTH_TOKENS", json.dumps({"test": {"developer_id": "test"}}))

    async def migrate(*args):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, stdout.decode() + stderr.decode()

    await migrate("upgrade", "0001")
    snapshot = {"id": "external-task", "name": "Existing task", "state": {"id": "open"}}
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("project", "demo", "Demo", "team", "plane-project", "[]", "{}"),
        )
        db.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?)",
            ("task", "project", "external-task", json.dumps(snapshot), None),
        )
        db.execute(
            "INSERT INTO work_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session", "task", "alice", "codex", "repo", "main", None, "2026-10-07"),
        )
        db.execute(
            "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("report", "task", "session", "alice", "key", "hash", "{}", "history", "2026-10-07"),
        )
        db.execute(
            "INSERT INTO outbox VALUES (?, ?, ?, ?, ?, ?)",
            ("job", "report", "pending", 0, "2026-10-07", None),
        )
    await migrate("upgrade", "head")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT tracker_provider, tracker_workspace, tracker_project_id FROM projects"
        ).fetchone() == ("plane", "team", "plane-project")
        external_id, stored = db.execute("SELECT external_id, snapshot FROM tasks").fetchone()
        assert external_id == "external-task"
        assert json.loads(stored) == snapshot
        assert TaskSnapshot.model_validate(json.loads(stored)).state_id == "open"
        assert db.execute("SELECT id, payload_hash FROM reports").fetchone() == ("report", "hash")
        assert db.execute("SELECT report_id, status FROM outbox").fetchone() == (
            "report",
            "pending",
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    await migrate("downgrade", "0001")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT plane_item_id FROM tasks").fetchone() == ("external-task",)
        assert db.execute("SELECT plane_project_id FROM projects").fetchone() == ("plane-project",)
