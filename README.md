# Project Context Service

Общий контекст проектов и история работы ИИ-агентов: **FastAPI + PostgreSQL + Plane + MCP**.

REST и MCP используют одну бизнес-логику и проверку доступа. PostgreSQL хранит
историю работы, таск-трекер остаётся источником текущих требований и статуса задачи.
Plane — первая реализация общего интерфейса `TaskTracker`.

## Интерфейс таск-трекера

Контракт расположен в `app/trackers/base.py`, реализация Plane — в
`app/trackers/plane.py`. Сервис и worker зависят от интерфейса, получают нормализованный
`TaskSnapshot` и не работают с HTTP или специфичными полями Plane.

Методы интерфейса: `get_task`, `get_task_context`, `transition_task`, `publish_report`.
Адаптер получает DTO `TrackerProject` и строковый внешний ID вместо ORM-объектов.
Plane проверяет UUID внутри своего адаптера; другие реализации могут использовать
собственные форматы ID задач и состояний.

Для другого трекера:

1. Реализуйте `TaskTracker`, возвращая `TaskSnapshot`/`TaskContext`.
2. Добавьте фабрику в `app/trackers/factory.py` и настройки авторизации адаптера.
3. Укажите `TASK_TRACKER_PROVIDER` и тот же `tracker_provider` при создании проекта.

В тестах можно передать готовую реализацию через `create_app(settings, tracker=adapter)`.
Один процесс API/worker использует один выбранный адаптер. Проекты другого провайдера
отклоняются; автоматического маршрутизатора нескольких трекеров пока нет.

Новые поля API: `tracker_provider`, `tracker_workspace`, `tracker_project_id`,
`external_id`. Контекст возвращается в `tracker` с `provider`, `snapshot` и `freshness`;
статус публикации отчёта — в `tracker_sync`. Старые входные поля `plane_workspace`,
`plane_project_id`, `plane_item_id` и ответы `plane`, `plane_sync` сохранены как алиасы
для клиентов Plane. Основные примеры ниже с прежними именами продолжают работать.

После обновления примените `uv run alembic upgrade head`. Миграция 0002 сохраняет
старые Plane-привязки, отчёты и задания worker, переводя таблицы на нейтральные имена.
`TRACKER_SYNC_REPORTS` заменяет `PLANE_SYNC_REPORTS`; старое имя окружения также принимается.

## Что реализовано

- Проекты с разрешёнными репозиториями и привязкой к Plane workspace/project.
- Индивидуальные bearer-токены: разработчик, роль reader/writer/admin, доступные проекты.
- Регистрация задач по Plane UUID и сессии конкретного разработчика/агента.
- Неизменяемые отчёты, защита от повторной отправки и конкурентных дублей.
- Связи задачи с ветками, PR и несколькими коммитами, включая отчёты без коммита.
- Контекст: актуальная задача Plane, свежесть данных, документы конкретной ревизии,
  последние сессии, отчёты и Git-связи. При отказе Plane — явно помеченная копия.
- История отчётов с пагинацией и события наблюдаемых изменений статуса.
- Загрузка Markdown из Git по точному SHA и чтение полных документов.
- Полнотекстовый поиск PostgreSQL с GIN. Embeddings/pgvector не требуются для MVP.
- Явная смена статуса Plane: admin, ожидаемый текущий статус, allowlist переходов.
- Опциональная публикация отчётов в комментарии Plane через transactional outbox,
  отдельный worker, повторные попытки и поиск уже отправленного комментария.
- Настоящий MCP Streamable HTTP на `/mcp/`, REST/OpenAPI на `/docs`.
- Alembic, Docker Compose, тесты и GitHub Actions с PostgreSQL 17.

## Быстрый запуск через Docker

В PowerShell:

```powershell
Copy-Item .env.example .env
```

В `.env` замените токены в `AUTH_TOKENS`, укажите `PLANE_API_KEY` и при необходимости
URL вашего self-hosted Plane. Версия API задаётся `PLANE_API_VERSION=v1` или `v2`.
Проверьте доступность выбранной версии на вашем экземпляре Plane.
API v2 не возвращает описание задачи: сервис получает его через v1 detail endpoint.
Если v1 недоступен, контекст содержит предупреждение о недоступных требованиях.
Для разработки пароль PostgreSQL по умолчанию — `context`; для размещения сервиса
задайте собственный `POSTGRES_PASSWORD` в `.env`.

```powershell
docker compose up --build -d
```

Compose запустит PostgreSQL, применит миграции, затем API и worker.
API: `http://localhost:8000`; Swagger: `http://localhost:8000/docs`;
MCP: `http://localhost:8000/mcp/`.
В Swagger нажмите **Authorize** и введите bearer-токен.

При публикации через reverse proxy добавьте его домен в `MCP_ALLOWED_HOSTS`,
разрешённые browser origins — в `MCP_ALLOWED_ORIGINS`. Пример:
`["context.example.com"]` и `["https://context.example.com"]`. HTTPS завершается на proxy.

Публикация комментариев выключена по умолчанию. Чтобы включить её, задайте
`PLANE_SYNC_REPORTS=true`. Этот флаг действует на новые отчёты; уже созданные
задания worker обрабатывает независимо от флага.

## Запуск без Docker

Нужен Python 3.12+ и работающий PostgreSQL:

```powershell
uv sync --locked
Copy-Item .env.example .env
# Настройте .env перед следующими командами.
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Для запуска REST и MCP без admin access key (bearer-токена):

```powershell
uv run python -m app --no-auth
```

В этом режиме `AUTH_TOKENS` не требуется: все запросы получают серверную identity
`local-admin` с ролью admin и доступом ко всем проектам. Сессии и отчёты записываются
от её имени. Используйте этот режим в доверенном окружении. По умолчанию CLI слушает
`127.0.0.1:8000`; адрес и порт задаются через `--host` и `--port`. Без `--no-auth`
авторизация включена. Также доступна настройка `AUTH_DISABLED=true`.

Worker в отдельном терминале:

```powershell
uv run python -m app.worker
```

## Подготовка проекта

1. Создайте проект через `POST /api/projects` с admin-токеном.
2. Зарегистрируйте задачу через `POST /api/projects/{project_id}/tasks` с Plane
   work-item UUID. В ответе — отдельный UUID задачи этого сервиса.
3. Загрузите документы из нужного Git-коммита либо дайте агенту читать их локально.
4. Подключите MCP с персональным токеном разработчика.

Пример создания проекта в PowerShell:

```powershell
$contextHeaders = @{ Authorization = "Bearer $env:CONTEXT_API_TOKEN" }
$contextProject = @{
  slug = "demo"
  name = "Demo project"
  repositories = @("team/payments")
  plane_workspace = "my-workspace"
  plane_project_id = "00000000-0000-0000-0000-000000000001"
  allowed_transitions = @{}
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/projects `
  -Headers $contextHeaders -ContentType application/json -Body $contextProject
```

Замените UUID и workspace своими значениями. По умолчанию смена статуса запрещена.
Для разрешения переходов при создании проекта задайте `allowed_transitions`:
ключ — UUID исходного состояния, значение — список UUID допустимых следующих состояний.
Создание/редактирование самих состояний в Plane этот сервис не выполняет.

Управление конфигурацией существующих проектов в этом MVP выполняется администратором
в БД; публичного PATCH проекта пока нет.

## Документы проекта

Рекомендуемая структура в каждом рабочем репозитории:

```text
AGENTS.md
docs/agents/
  project.md
  architecture.md
  testing.md
  workflow.md
  decisions/
```

Из рабочего Git checkout запустите скрипт этого сервиса. Токен должен принадлежать
admin, доступному данному проекту; секрет передаётся через `CONTEXT_API_TOKEN`:

```powershell
python C:/path/to/project-context-service/scripts/sync_docs.py `
  --project-id PROJECT_UUID --repo team/payments --ref HEAD
```

Скрипт разрешает ref в SHA, читает только tracked Markdown `AGENTS.md` и `docs/agents`
из этого коммита, пропускает symlinks и загружает файлы через REST. Сервис хранит
документы с ключом `project + repo + SHA + path`. Запрашивайте контекст с этим SHA.
Незакоммиченные документы агент читает локально. Импорт можно запускать из доверенного CI.

## MCP-инструменты

| Инструмент | Назначение |
|---|---|
| `list_projects` | Доступные проекты и репозитории |
| `register_task` | Регистрация задачи Plane, возвращает локальный task UUID |
| `get_task_context` | Контекст задачи; `task_id`, `repo`, `ref`, `refresh` |
| `read_project_document` | Полный документ по ID из контекста/поиска |
| `get_task_history` | История отчётов, `cursor`, `limit` |
| `find_related_context` | Поиск внутри проекта, опционально repo/ref |
| `start_work_session` | Создание сессии разработчика с repo/branch/base SHA |
| `submit_work_report` | Добавление отчёта с idempotency key |
| `transition_task` | Отдельный admin-only переход статуса Plane |

URL MCP: `http://localhost:8000/mcp/`, transport: **Streamable HTTP**.
Каждый запрос должен содержать `Authorization: Bearer TOKEN`.
Используйте header-конфигурацию MCP-клиента; OAuth discovery в MVP отсутствует.
Для клиентов без возможности передать bearer header потребуется поддерживающий
это proxy/bridge или добавление OAuth авторизации в сервис.

Пример JSON-конфигурации для клиентов с `mcpServers` и HTTP headers:

```json
{
  "mcpServers": {
    "project-context": {
      "url": "http://localhost:8000/mcp/",
      "headers": {"Authorization": "Bearer YOUR_PERSONAL_TOKEN"}
    }
  }
}
```

Не коммитьте файл с реальным токеном. Храните персональную конфигурацию локально
или используйте поддерживаемую клиентом подстановку секрета из окружения.

В `AGENTS.md` рабочих проектов закрепите порядок:
получить контекст → проверить актуальность → начать сессию → внести изменения →
провести проверки → отправить отчёт. Этот сервер не заставляет агент автоматически
выполнять данный порядок: его должен закрепить клиент/инструкция команды.

## Репозитории и список задач

Администратор может добавить репозитории в существующий проект через
`POST /api/projects/{project_id}/repositories` с телом
`{"repositories": ["team/backend", "team/frontend"]}` или MCP-инструмент
`add_project_repositories(project_id, repositories)`. Старые репозитории сохраняются,
повторы не добавляются. Общий лимит — 30 репозиториев; конфликт параллельных изменений
возвращает 409 и требует повтора запроса.

`GET /api/projects/{project_id}/tasks?limit=20` и MCP-инструмент
`list_tracker_tasks(project_id, cursor, limit)` возвращают живой список из трекера,
включая задачи без локальной регистрации. Доступ разрешён читателям в области проекта.
Ответ содержит `tasks`, `next_cursor`, `freshness` и `fetched_at`; для следующей страницы
передайте `next_cursor` как `cursor`. Лимит страницы — от 1 до 100.
При недоступности трекера возвращается ошибка, без подмены списка кешем.
Выбранную задачу зарегистрируйте через `register_task`, передав её `id` как `external_id`.
Plane поддерживает список в v1/v2; другие адаптеры реализуют `TaskTracker.list_tasks`
или возвращают 501. Просмотр списка не создаёт локальных задач и не меняет их статус.

## Пример отчёта

`POST /api/tasks/{task_id}/reports` либо параметр `report` инструмента `submit_work_report`:

```json
{
  "session_id": "00000000-0000-0000-0000-000000000002",
  "idempotency_key": "session-2-checkpoint-1",
  "outcome": "handoff",
  "summary": "Добавлена идемпотентная обработка повторов",
  "decisions": ["Повторный запрос использует сохранённый результат"],
  "blockers": [],
  "next_steps": ["Ревью", "Проверка на staging"],
  "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "commits": ["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
  "pr_url": "https://git.example/team/payments/pull/42",
  "dirty_worktree": false,
  "checks": [{
    "command": "pytest tests/payments",
    "result": "passed",
    "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "evidence": "18 passed"
  }]
}
```

`developer_id` берётся из токена. Чужую сессию нельзя использовать даже с admin-токеном.
Одинаковая повторная отправка возвращает существующий отчёт; изменённый payload
с тем же ключом даёт HTTP 409. Отчёт не меняет статус задачи.

## Проверки и ограничения

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Для настоящего PostgreSQL используйте **отдельную тестовую БД**:

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://context:context@localhost:5432/context_test"
uv run pytest -q
```

Тесты применяют и откатывают миграции, удаляя таблицы. Не направляйте их на рабочую БД.
По умолчанию они используют SQLite и mock Plane; PostgreSQL trigger-тест пропускается.
CI запускает весь набор на PostgreSQL 17. Проверка реального Plane требует ваших
credentials и тестового workspace.

В MVP Git-связи и результаты проверок поступают от агента и явно помечаются как
непроверенные. Автоматическое чтение Git/CI и incoming webhooks пока не реализованы.
История Plane содержит снимки/наблюдаемые изменения, а не все события трекера.
Публикация комментариев даёт at-least-once delivery с best-effort дедупликацией;
Plane не гарантирует уникальность external ID. Смена статуса через GET/PATCH
не является атомарной операцией относительно других пользователей Plane.

Подробности: [архитектура](docs/agents/architecture.md),
[тестирование](docs/agents/testing.md), [процесс агентов](docs/agents/workflow.md).
