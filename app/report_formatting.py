"""Map a saved report to readable, provider-neutral tracker text."""

from datetime import UTC

from app.models import Report


def _items(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "Нет."


def _checks(checks: list[dict]) -> str:
    sections = []
    for check in checks:
        lines = [f"{check['result']}: {check['command']}"]
        for field, label in (
            ("commit_sha", "Проверенный SHA"),
            ("evidence", "Результат"),
            ("ci_run_url", "CI"),
        ):
            if check.get(field):
                lines.append(f"{label}: {check[field]}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) if sections else "Проверки не указаны."


def format_report(report: Report, agent_client: str) -> str:
    payload = report.payload
    developer = report.developer_id
    if report.developer_name:
        developer = f"{report.developer_name} ({developer})"
    created_at = report.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    git = [
        f"HEAD: {payload['head_sha'] or 'не указан'}",
        f"Рабочее дерево: {'изменено' if payload['dirty_worktree'] else 'чистое'}",
        "Коммиты:\n" + _items(payload["commits"]),
    ]
    for field, label in (("pr_url", "PR"), ("artifact_url", "Артефакт")):
        if payload.get(field):
            git.append(f"{label}: {payload[field]}")
    return "\n\n".join(
        [
            f"Отчёт о работе\nДата: {created_at.isoformat()}\n"
            f"Разработчик: {developer}\nАгент: {agent_client}\n"
            f"Результат работы: {payload['outcome']}",
            "Краткое описание:\n" + payload["summary"],
            "Решения:\n" + _items(payload["decisions"]),
            "Git:\n" + "\n".join(git),
            "Проверки (сообщены агентом):\n" + _checks(payload["checks"]),
            "Ограничения и блокеры:\n" + _items(payload["blockers"]),
            "Дальнейшие действия:\n" + _items(payload["next_steps"]),
            f"Идентификаторы:\nЗадача Shared Access: {report.task_id}\n"
            f"Сессия: {report.session_id}\nОтчёт Shared Access: {report.id}",
        ]
    )
