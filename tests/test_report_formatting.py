from datetime import UTC, datetime
from types import SimpleNamespace

from app.report_formatting import format_report
from app.trackers.plane import render_report_html


def test_report_separates_sections_and_formats_checks_without_python_repr():
    report = SimpleNamespace(
        id="report-1",
        task_id="task-1",
        session_id="session-1",
        developer_id="alice",
        developer_name="Alice",
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
        payload={
            "outcome": "implemented",
            "summary": "Task: upload\n\nFixed bounded connections.",
            "head_sha": "a" * 40,
            "dirty_worktree": False,
            "commits": ["a" * 40],
            "decisions": ["Keep old snapshot"],
            "blockers": [],
            "next_steps": ["Verify staging"],
            "checks": [
                {
                    "command": "pytest -q",
                    "result": "passed",
                    "commit_sha": "a" * 40,
                    "evidence": "33 passed",
                },
            ],
        },
    )
    content = format_report(report, "Codex")
    assert "\n\nРешения:\n- Keep old snapshot\n\nGit:\n" in content
    assert "passed: pytest -q\nПроверенный SHA: " + "a" * 40 in content
    assert "Результат: 33 passed" in content
    assert "'command':" not in content
    assert "Разработчик: Alice (alice)\nАгент: Codex" in content
    assert "Дата: 2026-10-15T00:00:00+00:00" in content
    assert "\n\nОграничения и блокеры:\nНет." in content
    assert "Отчёт Shared Access: report-1" in content


def test_plane_report_preserves_paragraphs_and_escapes_untrusted_html():
    content = "Результат:\r\nГотово <script>alert(1)</script>\r\n\r\nПроверки:\r\npytest\n\n"
    assert render_report_html(content) == (
        "<p><strong>Результат:</strong><br>Готово &lt;script&gt;alert(1)&lt;/script&gt;</p>"
        "<p><strong>Проверки:</strong><br>pytest</p>"
    )


def test_empty_report_does_not_create_empty_html_paragraphs():
    assert render_report_html("\n\n \n\n") == ""
