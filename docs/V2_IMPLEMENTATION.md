# V2: имплементация AGENTS.md — карта соответствия

Дата: 25 июля 2026 · Статус: MVP + Фаза 2 ПОЛНОСТЬЮ (включая платежи)

Этот документ фиксирует, какие разделы [AGENTS.md](../AGENTS.md) реализованы,
какие решения приняты и что сознательно отложено. V2-слой включается флагом
`RADAR_V2_ENABLED` и по умолчанию **выключен** — поведение существующего бота
не меняется (§12.4: дисциплина scope).

## Карта: спека → код

| Раздел спеки | Реализация | Тесты |
|---|---|---|
| §3.1 Мониторинг, адаптеры `fetch() -> list[RawListing]` | `monitoring/adapters/` (base, kwork, telegram_channels, fl_ru) | `test_v2_adapters.py` |
| §3.1 Дедупликация `(source, external_id)` + fuzzy | `monitoring/collector.py` | `test_v2_collector.py` |
| §3.2 Экстракция (дешёвая модель, строгий JSON) | `core/generation.py::extract_listing` + `prompts/extraction_v1.md` | `test_v2_generation.py` |
| §3.3 Скоринг вероятности (логистическая формула, без LLM) | `core/scoring.py::win_probability` + нормализация 5 признаков | `test_v2_scoring.py` |
| §3.4 Выгодность, светофор 🟢🟡🔴 | `core/scoring.py::compute_profitability` | `test_v2_scoring.py` |
| §3.5 Генерация отклика 80–150 слов, без клише, с CTA | `core/generation.py::generate_proposal` + `prompts/proposal_v1.md` | `test_v2_generation.py` |
| §3.6 Адаптация портфолио (переранжирование кейсов + вводная строка) | `core/generation.py::select_relevant_cases`, `generate_portfolio_intro` | `test_v2_generation.py` |
| §3.7 CRM-воронка (ровно по диаграмме) | `core/crm.py::ALLOWED_TRANSITIONS`, `change_stage` | `test_v2_crm.py` |
| §3.8 Напоминания (48ч/24ч, «написать сейчас»/«отложить») | `core/crm.py` + `monitoring/worker.py::run_reminders_tick` | `test_v2_crm.py`, `test_v2_worker.py` |
| §4.1 Пайплайн Collector → Scoring → Generation → Bot | `monitoring/worker.py::run_radar_tick` | `test_v2_worker.py` |
| §4.2 PostgreSQL / SQLAlchemy async | `core/db.py` (DATABASE_URL: asyncpg в проде, aiosqlite в dev) | `test_v2_llm_db.py` |
| §4.3 Структура репозитория | `core/`, `monitoring/`, `prompts/`, `alembic/` созданы | — |
| §5 Модель данных (10 сущностей) | `core/models.py` | `test_v2_models.py`, `test_v2_migrations.py` |
| §6.1–6.2 Две модели по стоимости | `core/llm.py` + `EXTRACTION_MODEL`/`GENERATION_MODEL` | `test_v2_llm_db.py` |
| §6.3 Версионированные промпты в `prompts/` | `prompts/*.md`, `load_prompt()` | `test_v2_generation.py` |
| §6.4 Guardrails (только PortfolioItem, ручная проверка, ретрай) | `core/generation.py::validate_proposal`, `GuardrailError` | `test_v2_generation.py` |
| §7 Тарифы 299/599/999 ₽, лимиты, триал 7 дней | `core/tariffs.py` | `test_v2_tariffs.py` |
| §7 Гейтинг в боте (источники, анализы, CRM, AI) | хендлеры + `monitoring/worker.py` (квоты) | `test_v2_handlers*.py`, `test_v2_worker.py` |
| Бот: онбординг/портфолио/отклики/CRM/подписка | `bot/handlers/v2/` (`/radar`, `/portfolio`, `/clients`, `/subscription`, `/grant`) | `test_v2_handlers*.py` |
| Alembic-миграции | `alembic/` + автогенерированная `66c6c53196b8` | `test_v2_migrations.py` |

## Принятые решения (и почему)

1. **Фиче-флаг `RADAR_V2_ENABLED`** — ноль незапрошенных изменений в проде
   (§12.4). Диф в `main.py` минимален и полностью изолирован флагом.
2. **Конфликт в спеке про автоотправку**: §2.4 говорит «только Business»,
   §3.5 и §6.4 — «Pro/Business». Принято Pro/Business (двойное упоминание,
   включая нормативный раздел guardrails); всегда opt-in + порог скоринга.
3. **`ProjectAnalysis.user_id` добавлен** к упрощённой модели §5: вероятность
   и выгодность считаются от профиля конкретного пользователя (§3.3), общая
   запись анализа невозможна в multi-tenant.
4. **`ExchangeConnection.settings` (JSON)** — несекретные настройки адаптера
   (username TG-канала). Секреты по-прежнему только через `credentials_ref` (§5, §8).
5. **Триал = уровень Pro** на 7 дней (в §7 уровень триала не специфицирован).
6. **Частота опроса** (§12.7): V2-тик переиспользует `MONITOR_INTERVAL_MINUTES`
   легаси-монитора; «приоритетная частота сканирования» Business реализована как
   приоритет очереди уведомлений, а НЕ ускорение скрапинга — изменение частоты
   требует отдельного согласования.
7. **skill_match — эвристика** (пересечение навыков/тегов), не embeddings:
   дорожная карта §14 прямо требует «эвристический скоринг без ML» для MVP;
   интерфейс готов к замене на embedding-версию в Фазе 3.
8. **Без LLM-ключа пайплайн работает**: экстракция падает обратно на бюджеты
   из парсеров, Basic-шаблон отклика детерминированный. LLM обязателен только
   для AI-генерации (Pro+).
9. **«Отправка» отклика = фиксация в системе**: реальная публикация отклика на
   бирже требует биржевых учёток пользователя (vault, §5 `credentials_ref`) и
   отложена; кнопка «Отправлено» фиксирует факт, создаёт карточку CRM и
   напоминание. Автоотправка (Pro+) в этой версии готовит и автоподтверждает
   черновик, но не публикует на биржу.
10. **Postgres через DATABASE_URL**: в dev/тестах — SQLite (aiosqlite), в
    проде — `postgresql+asyncpg://` (§4.2). Alembic-миграция едина для обоих.
11. **poetry не внедрён** (§9 упоминает `poetry install`): деплой Railway и CI
    собираются от `requirements.txt`; конвертация — отдельная инфраструктурная
    задача, чтобы не рисковать пайплайном деплоя в этом же изменении.

## Фаза 2 — реализовано (25.07, вечер)

- **Telegram Payments / ЮKassa** (§7, §4.2 «оплата не покидая Telegram»):
  кнопки оплаты в `/subscription` → `send_invoice` → валидация
  `PreCheckoutQuery` (payload + сумма против таблицы §7, клиенту не доверяем)
  → идемпотентная активация по `telegram_payment_charge_id`
  (unique-ограничение + savepoint; повторная доставка апдейта — no-op).
  Продление того же тарифа наращивает срок от текущего окончания; смена
  тарифа стартует новые 30 дней. Код: `core/billing.py`,
  `bot/handlers/v2/payments.py`, миграция `d4f51504d763`. Включается
  переменной `PAYMENT_PROVIDER_TOKEN` (BotFather → Payments → ЮKassa);
  без токена кнопки отвечают «скоро», ручной `/grant` остаётся.
  54-ФЗ чеки — настройка на стороне ЮKassa (personal/self-employed режимы).
- **Недельный отчёт Pro/Business** (§7): cron по понедельникам 09:00 МСК —
  анализы за неделю, лучшая вероятность, отправленные отклики, активная
  воронка. Пустые недели не шумят.
- **PostgreSQL подтверждён на реальном сервере**: все 3 миграции, unique- и
  partial-ограничения, savepoint-паттерны и идемпотентность биллинга
  проверены на PostgreSQL 16.4 (`tests/integration/test_postgres_smoke.py`,
  активируется `TEST_PG_URL`; прод Railway — Postgres-плагин).

## Отложено (по дорожной карте §14)

- **Фаза 2 (хвост):** Weblancer-адаптер, годовая оплата −20% кнопкой.
- **Фаза 3:** веб-дашборд (`api/` FastAPI + `web/` Next.js), embedding-версия
  skill_match, дообучение весов на личной истории (§3.3 «холодный старт»).
- **Фаза 4:** командные аккаунты, экспорт Notion/Sheets, публичное API,
  Upwork-адаптер, реальная автоотправка через биржевые учётки (vault).

## Качество (§11, §12.1)

После двойного AI-аудита (Architect + Developer, 25.07.2026):

- `pytest`: **369 passed, 0 failed** — включая 9 ранее падавших легаси-тестов
  (исправлены корневые причины: формат `FilterReason` на Py3.11 и
  неустойчивость `BlacklistService` к неинициализированной БД).
- Покрытие V2-модулей: **94%**.
- `ruff check .`: чисто.
- `mypy --ignore-missing-imports --follow-imports=silent core monitoring
  bot/handlers/v2`: **0 ошибок** (CI-гейт). Полный прогон по репозиторию
  (~900 ошибок в легаси-коде) — задокументированный долг постепенной
  типизации, в CI выполняется информационно (`|| true`).
- Alembic: `upgrade head` применяется с нуля и инкрементально; прод-старт
  идёт через `run_v2_migrations()` (не `create_all`), поэтому
  `alembic_version` ведётся с первого запуска.

Ключевые прод-гарантии после аудита: экстракция LLM — 1 раз на листинг
(§3.2); уведомления отправляются только после commit; напоминания —
at-most-once (§3.8); дубли исключены ограничениями БД
(`project_analyses(project_id,user_id)`, `clients(user_id,platform_client_id)`,
частичный уникальный индекс на биржевые подключения); адаптеры и LLM-клиент
закрываются (`post_shutdown`); healthcheck реально работает; состояние
PTB-диалогов переживает рестарт (PicklePersistence).

## Что нельзя проверить автоматически (§12.6)

- [ ] Живой прогон `/radar` онбординга в реальном Telegram (клавиатуры, эмодзи).
- [ ] Реальный Kwork-скрапинг через Playwright под V2-адаптером (в тестах — моки, §11).
- [ ] Реальные вызовы OpenRouter: качество экстракции и откликов на боевых моделях.
- [ ] FL.ru: актуальность HTML-селекторов на живой странице.
- [ ] Поведение на PostgreSQL под нагрузкой (миграция проверена на SQLite).
- [ ] Визуальная проверка карточек (HTML-разметка) в клиентах Telegram.
