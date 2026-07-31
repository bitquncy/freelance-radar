# Комплексный аудит FreelanceRadar — 31.07.2026

## Executive summary

Проект в целом имеет сильную unit-test базу (426 passed, покрытие выбранной целевой поверхности 94%), корректные tenant ownership-проверки в большинстве V2 callback-handlers, серверную валидацию платежной суммы и уникальность charge ID. Однако до production остаются существенные риски параллельной работы и эксплуатации.

Главные выводы:

1. **HIGH:** активация двух разных платежей одного пользователя не сериализована и может потерять оплаченные 30 дней.
2. **HIGH:** claim напоминания не атомарен в PostgreSQL; два worker/process могут отправить одно напоминание дважды.
3. **HIGH:** Docker-конфигурация по умолчанию запускает V2 на SQLite вопреки обязательному PostgreSQL для multi-tenant production.
4. **MEDIUM:** reminder callback позволяет связать reminder одного клиента с другим client ID того же пользователя.
5. **MEDIUM:** TG-channel duplicate/limit check не защищён constraint/lock и обходится параллельными сообщениями.
6. **MEDIUM:** healthcheck не проверяет V2/PostgreSQL и игнорирует провал disk probe.
7. **MEDIUM:** отсутствуют backup/restore и data-retention процедуры.

Аудит read-only: исходные пользовательские изменения не сбрасывались и не редактировались. Единственный созданный файл — этот отчёт согласно заданному output contract.

## Findings

### HIGH-1 — Lost update при двух разных успешных платежах

**Файлы:** `core/billing.py:117-126`, `core/billing.py:160-164`; вызов/commit — `bot/handlers/v2/payments.py:158-166`.

**Доказательство/сценарий:** `apply_paid_subscription()` читает `user.subscription_expires_at`, вычисляет `period_end`, затем обновляет объект User без `SELECT ... FOR UPDATE`, advisory lock или атомарного SQL. Два параллельных `successful_payment` с разными (поэтому оба допустимыми) charge ID могут прочитать одинаковый expiry, оба записать `base + 30 дней`; оба payment records сохранятся, но итоговая подписка продлится только на 30, а не 60 дней. Unique constraint по charge ID защищает только повтор одного charge, не два разных платежа.

**Remediation:** в PostgreSQL блокировать строку пользователя `SELECT ... FOR UPDATE` до расчёта expiry либо выполнять сериализованное атомарное обновление; payment insert и user update оставлять в одной транзакции. Добавить PostgreSQL integration test с двумя отдельными charge ID и барьером конкурентного старта, ожидающий +60 дней.

### HIGH-2 — Неатомарный claim due reminder допускает двойную отправку

**Файл:** `monitoring/worker.py:468-498`.

**Доказательство/сценарий:** оба worker сначала делают `session.get(Reminder, id)` (`:478`) и видят PENDING, затем оба переводят объект в NOTIFIED и commit. Нет `FOR UPDATE SKIP LOCKED` и нет conditional `UPDATE ... WHERE status='pending' RETURNING`. Заявленная в docstring атомарность/at-most-once не обеспечивается между процессами; оба caller получат claimed tuple и отправят Telegram message.

**Remediation:** PostgreSQL claim через conditional update с `RETURNING`, либо `SELECT FOR UPDATE SKIP LOCKED`; продолжать send только при rowcount=1. Покрыть реальным PostgreSQL parallel test в двух сессиях.

### HIGH-3 — Production Docker path фактически SQLite

**Файлы:** `docker-compose.yml:18-19`, `docker-compose.yml:45-67`; `config.py:59-62`.

**Доказательство/сценарий:** bot service безусловно переопределяет `DATABASE_URL=sqlite+aiosqlite:///data/...`; PostgreSQL service лишь закомментирован. Это противоречит `AGENTS.md §4.2` и оставляет multi-process транзакционные/locking гарантии непроверенными. Даже значение из `.env` будет перекрыто compose environment.

**Remediation:** отдельный production compose/profile с обязательным PostgreSQL, `depends_on` по healthy, secret-backed password и fail-fast запретом SQLite при production environment. SQLite оставить только dev/test override.

### MEDIUM-1 — Spoofed reminder/client pair вызывает побочный эффект не для связанного клиента

**Файл:** `bot/handlers/v2/crm_handlers.py:210-236`.

**Доказательство/сценарий:** callback содержит оба ID. Проверяется, что reminder существует и `client.user_id == user.id`, но не проверяется `reminder.client_id == client.id`. Пользователь может подставить свой другой client ID: будет завершено одно напоминание, а interaction/last_contact записаны другому клиенту.

**Remediation:** получать client исключительно по `reminder.client_id` либо явно требовать равенство. Добавить spoofing test на два клиента одного tenant.

### MEDIUM-2 — Параллельное добавление TG-канала обходит duplicate/limit

**Файл:** `bot/handlers/v2/sources.py:213-256`; схема — `core/models.py:180-189`.

**Доказательство/сценарий:** save-time recheck полезен последовательно, но две сессии одновременно прочитают одинаковый список (`:220-230`), обе пройдут limit/duplicate и commit. Partial unique index намеренно исключает `tg_channel`, а уникального нормализованного channel key нет. Итог — дубликат и/или превышение тарифа.

**Remediation:** нормализованный channel identifier в отдельной колонке с unique `(user_id, platform, channel_normalized)`; для конечных quota — lock строки User либо serializable/atomic quota allocation. PostgreSQL concurrency test.

### MEDIUM-3 — Healthcheck даёт ложный healthy

**Файл:** `scripts/healthcheck.py:56-70`; compose target — `docker-compose.yml:34-39`.

**Доказательство/сценарий:** probe всегда открывает legacy SQLite `DB_PATH`, не `DATABASE_URL`; PostgreSQL/V2 может быть недоступен, а контейнер останется healthy. `disk_ok` печатается, но условие успеха `if db_ok and log_ok` (`:64`) его игнорирует.

**Remediation:** dialect-aware `SELECT 1` по production `DATABASE_URL`, отдельно проверять обязательные хранилища; включить `disk_ok` в exit condition; при V2 проверить миграционный head/readiness.

### MEDIUM-4 — Нет backup/restore и проверяемой DR-процедуры

**Файлы:** `docker-compose.yml:45-67`, `DEPLOYMENT_CHECKLIST.md` (операционного scripted backup/restore не найдено), `scripts/` (нет backup/restore tooling).

**Доказательство:** repository-wide поиск `backup|restore|pg_dump` нашёл только log rotation/комментарии, не backup БД. Docker volume сам по себе не backup. Нет documented RPO/RTO и restore drill.

**Remediation:** автоматические encrypted PostgreSQL backups (`pg_dump`/managed PITR), retention policy, off-host copy, регулярный restore test и runbook; отдельно включить PTB persistence и legacy data, если они production-critical.

### MEDIUM-5 — Нет data-retention/purge механизма

**Файлы:** модели данных `core/models.py`; worker jobs `monitoring/worker.py:690-730`.

**Доказательство:** нет purge jobs/политики для raw project payloads, interactions, proposals, payment metadata и user deletion workflow. Имеется лишь cleanup legacy blacklist и ротация логов.

**Remediation:** утвердить сроки хранения по типам данных; реализовать owner-scoped export/delete и scheduled purge/anonymization; документировать исключения для финансового учёта.

### LOW-1 — FSM persistence локальная и небезопасна для нескольких replicas

**Файлы:** `main.py:177-187`; warnings `bot/handlers/v2/onboarding.py:180`, `bot/handlers/v2/portfolio.py:205`.

**Доказательство:** `PicklePersistence` хранится локально; compose монтирует `data`, но при нескольких replicas общий pickle небезопасен и не даёт распределённой синхронизации. Pytest также выдаёт PTB warning о callback tracking при `per_message=False`.

**Remediation:** до scale-out использовать singleton replica; затем Redis/DB-backed state с явной моделью FSM/locking. Проверить ожидаемую семантику ConversationHandler `per_message` и добавить restart/multi-update tests.

### LOW-2 — Runtime version drift

**Файлы:** `pyproject.toml:6`, `Dockerfile:5`; фактический coverage run.

**Доказательство:** проект требует Python >=3.11 и Docker использует 3.11, но локальные тесты выполнены Python 3.10.9. Тесты зелёные, однако этот прогон не аттестует заявленный runtime.

**Remediation:** CI gate на Python 3.11 (желательно exact minor, равный production image), запуск pytest/coverage/PostgreSQL integration именно там.

### LOW-3 — Ошибки Telegram логируются без traceback/context

**Файл:** `main.py:111-117`.

**Доказательство:** global handler пишет только `str(context.error)`; stack trace и update correlation отсутствуют, что ухудшает расследование runtime ошибок. Значения секретов в лог не обнаружены.

**Remediation:** логировать `exc_info=context.error`/sanitized update metadata, correlation ID; не включать message content/payment tokens.

## Что реализовано корректно

- Callback ownership: V2 clients, proposals, portfolio, sources и reminders в большинстве mutation paths проверяют `user_id` (`bot/handlers/v2/*`).
- Payment payload, tier, period и amount проверяются server-side (`core/billing.py:68-102`); charge ID уникален и duplicate delivery обрабатывается savepoint (`:128-158`).
- Proposal double-tap защищён conditional UPDATE/rowcount (`bot/handlers/v2/proposals.py:257-280`).
- HTML-escaping централизовано (`bot/handlers/v2/common.py:85-87`) и применено к scraped/user content в карточках (`bot/handlers/v2/cards.py`). URL ограничен http(s).
- Миграции V2 выполняются Alembic до старта (`main.py:164-172`), migration chain последовательна, новая migration добавляет expiry marker.
- `.env`, `*.session`, `*.db` игнорируются; `git ls-files` не показал tracked secret/database/session artifacts. Реальные значения `.env` не читались и не раскрываются.
- Логи ротируются 10 MB × 5 (`services/logger_config.py:14-16,32-37`); Docker json logs также ротируются.
- Emoji rendering имеет plain/HTML разделение и тесты; callback-data укладывается в короткие ASCII шаблоны.

## Тесты и проверки

| Команда | Результат |
|---|---|
| `python -m pytest -q` | **PASS:** 426 passed, 1 skipped, 2 PTB warnings, 29.39s |
| `python -m pytest --cov=core --cov=bot.handlers.v2 --cov=monitoring --cov-report=term-missing -q` | **PASS:** 426 passed, 1 skipped; target total **94%** (2491 stmts, 151 miss), 34.28s |
| `python -m ruff check .` | **PASS:** All checks passed |
| `python -m mypy --ignore-missing-imports .` | **PASS:** no issues in 83 source files |
| `git status --short`, `git diff --stat`, `git diff --cached --stat` | Read-only inspection; множество пользовательских modified/untracked файлов, staged diff отсутствует |
| `git ls-files` secret/session/db patterns + history path check | tracked `.env`/session/db не обнаружены |

Ограничение: skipped test и отсутствие доступного реального PostgreSQL означают, что concurrency/migration behavior PostgreSQL не подтверждён интеграционно. Coverage 94% относится к `core`, `bot.handlers.v2`, `monitoring`, не ко всему legacy repository.

## Матрица пунктов

| Пункт | Статус | Итог |
|---|---|---|
| Runtime/критические ошибки | Проверено/найдено | Runtime drift; критических deterministic startup crash по тестам не найдено |
| PostgreSQL/транзакции | Найдено | payment/reminder locking; production compose SQLite |
| Race conditions/double booking | Найдено | payment lost update, reminder double-send, TG quota race |
| Callback-data spoofing | Найдено | reminder/client pair; прочие inspected V2 ownership checks корректны |
| FSM | Проверено/риск | persistence есть, multi-replica unsafe, PTB warnings |
| User/admin/owner permissions | Проверено | legacy owner decorator; V2 tenant checks преимущественно корректны |
| Slot locks | Не применимо | booking slots в продукте отсутствуют; аналогичные locks оценены в races |
| Waitlist | Не применимо | функциональность отсутствует |
| Reminders | Найдено | non-atomic claim; expiry stamp at-most-once сознательно может потерять send |
| Backup/restore | Найдено | отсутствует DR implementation/runbook |
| Migrations | Проверено | Alembic chain/startup присутствуют; PostgreSQL live upgrade не удалось проверить |
| Idempotency | Найдено/проверено | charge/proposal constraints хороши; reminder claim дефектен |
| Payments/bonus spend | Найдено/частично N/A | payment race; bonus balance/spend отсутствует |
| Error handlers | Проверено/заметка | global handler есть, observability слабая |
| Telegram API | Проверено | precheckout validation, command publish best-effort; live API не вызывался |
| HTML/Markdown injection | Проверено | V2 escape корректен; явной exploitable injection не найдено |
| Emoji/rendering | Проверено | dedicated config/tests; warnings не про rendering |
| `.env`/secrets | Проверено | ignore/tracking корректны; локальные sensitive files существуют, не читались |
| Docker | Найдено | default V2 SQLite; healthcheck incomplete |
| Healthcheck | Найдено | не проверяет PostgreSQL/V2, игнорирует disk failure |
| Logging | Проверено/заметка | rotation есть; exception traceback/correlation слабые |
| Retention | Найдено | DB retention/user deletion отсутствуют |
| Tests/coverage | Проверено | 426 pass, target 94%, 1 skip, PostgreSQL concurrency gap |
| Production config | Найдено | SQLite default и нет explicit production fail-fast |
| Parallel-only bugs | Найдено | payment, reminders, TG channels |

## Residual risks

- Реальный PostgreSQL не был доступен, поэтому DDL partial index, enum behavior, migration rollback и конкурентные сценарии подтверждены код-анализом, но не live integration run.
- Не выполнялись Telegram/ЮKassa/Telethon/Playwright реальные вызовы; только unit/mock coverage.
- Worktree содержит крупный набор незакоммиченных пользовательских изменений; вывод относится именно к текущему состоянию на момент аудита.
- Legacy SQLite subsystem сосуществует с V2 SQLAlchemy schema; рассинхронизация operational ownership между двумя БД остаётся архитектурным риском.
- At-most-once strategy «commit before send» для reminders/expiry гарантированно допускает потерю уведомления при crash/network failure; это документированный trade-off, но требует продуктового подтверждения и метрик dead-letter/reconciliation.

## Review

- Correct: 426 тестов проходят; target coverage 94%; ruff и mypy зелёные; tenant checks/escaping/payment amount validation присутствуют.
- Blocker: `core/billing.py:117-164` — concurrent distinct payments can lose paid time.
- Blocker: `monitoring/worker.py:468-498` — reminder claim is not atomic across workers.
- Blocker: `docker-compose.yml:18-19` — production-shaped deployment defaults V2 to SQLite.
- Note: remediation и residual risks перечислены выше; production readiness требует PostgreSQL concurrency suite и DR/retention controls.