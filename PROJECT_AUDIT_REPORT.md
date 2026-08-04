# Комплексный профессиональный аудит FreelanceRadar

**Дата аудита:** 03.08.2026
**Ветка/коммит:** `fix/kwork-source` · `e792a64` (fix(kwork): parse current project state)
**Аудитор:** Senior QA / Security / UX / Product (15+ лет)
**Тип продукта:** Telegram-бот мониторинга фриланс-бирж (multi-tenant SaaS-слой V2 + legacy single-owner бот)

---

## Методология и объём проверки

Аудит выполнен по 10 направлениям промпта: функциональное тестирование, UX/UI, бизнес-логика,
безопасность, производительность, SEO (неприменимо — это бот, не сайт), Telegram-бот, edge cases,
автоматический поиск багов, итоговый отчёт.

**Фактически выполненные проверки (живой прогон):**
- `python -m pytest tests/unit -q` → **428 passed, 2 warnings** (18.4 c)
- `python -m pytest tests/integration tests/services -q` → **34 passed, 5 skipped, 1 warning** (16.6 c)
- `python -m ruff check .` → **All checks passed**
- `python -m mypy --ignore-missing-imports core monitoring bot/handlers/v2` → **Success: no issues in 29 source files**
- Статический code-review ключевых модулей: `core/` (billing, tariffs, scoring, generation, models, crm),
  `bot/auth.py`, `bot/commands.py`, `bot/handlers/v2/*`, `monitoring/worker.py`, `monitoring/collector.py`,
  `parsers/kwork.py`, `services/broadcast/*`, `docker-compose.yml`, `Dockerfile`, `scripts/healthcheck.py`,
  `scripts/entrypoint.sh`, `.gitignore`, `.env.example`, `prompts/*`.

**Контекст:** в репозитории уже есть два предыдущих read-only аудита (`.audit-runtime-security.md`,
`PROJECT_AUDIT_2026-07-31.md`). В данной ветке большинство их finding'ов **исправлено** — это
отмечено ниже как «FIXED». Отдельно выделены остаточные и новые проблемы.

---

## 1. ФУНКЦИОНАЛЬНОЕ ТЕСТИРОВАНИЕ

Проект имеет сильную тестовую базу (~462 теста). Проверка команд/кнопок/FSM выполнена по коду.

| Сценарий | Статус | Примечание |
|---|---|---|
| `/start`, `/radar`, `/menu`, `/portfolio`, `/clients`, `/subscription`, `/help` | OK | Зарегистрированы; native-команды пушатся в Telegram (`publish_bot_commands`) |
| Онбординг (ставка→налог→навыки) | OK | ConversationHandler с валидацией диапазонов и повтором при ошибке (`onboarding.py:78-127`) |
| Источники: добавить/toggle/удалить Kwork/FL.ru/TG-канал | OK | Перезапись лимита/дубликата «в момент сохранения» (`sources.py:189-258`) |
| Портфолио: add/delete, truncation 200/1500 символов | OK | `portfolio.py:99-118` |
| Отклики: generate/edit/regenerate/send/cases/hide | OK | Все 6 callback-паттернов зарегистрированы (`proposals.py:387-396`) |
| CRM: список/карточка/стадии/заметки/напоминания | OK | `crm_handlers.py:246-256` |
| Платежи: invoice→precheckout→successful_payment | OK | Серверная валидация суммы+валюты на обоих этапах (`payments.py:99-182`) |
| `/grant` (owner-only ручная выдача) | OK | `subscription.py:154-207` |
| `/search` (FTS5 с LIKE-fallback) | WARN | Работает, но на legacy SQLite-слое; в V2-режиме поиск по V2-проектам отсутствует |
| Поиск/фильтрация/пагинация вакансий | WARN | Реализованы только в legacy-слое; V2-проекты просматриваются только через push-уведомления |
| Уведомления (transactional outbox) | OK | `with_for_update(skip_locked=True)` + recovery stale (`worker.py:351-460`) |
| Недельный отчёт | OK | `run_weekly_report_tick`, честный, без шума при пустой неделе |
| Интеграции (OpenRouter, Playwright, Telethon, ЮKassa) | OK (mock) | В unit-тестах мокаются; live-вызовы не выполнялись |

**Функциональные дефекты:**

### F-1 (Low) — V2 не имеет браузера/поиска по проектам
- **Название:** В multi-tenant режиме нет команды просмотра истории заказов/поиска по V2-проектам.
- **Шаги:** Пользователь подключил источник → получает push-карточки → через неделю хочет посмотреть архив.
- **Ожидаемый:** команда `/projects` или раздел меню с пагинацией/фильтром по скорингу/источнику.
- **Фактический:** карточки приходят только пушем; `project_card_keyboard` даёт только «Отклик/Скрыть/Кейсы». Прокрутить историю нельзя. Legacy `/search` работает по отдельной SQLite-таблице `vacancies`.
- **Критичность:** Low (не блокирует MVP, но снижает удержание: «упущенный» заказ не возвращаем).
- **Файлы:** `bot/handlers/v2/menu.py`, `bot/handlers/v2/cards.py:97`.

### F-2 (Low) — Настройки legacy-фильтров недоступны в V2
- `filters_menu`/whitelist/blacklist/min-rating/max-proposals (`settings_handler.py`) привязаны к `OWNER_CHAT_ID` и legacy SQLite. В V2 ручных pre-filters (мин. рейтинг, стоп-слова) для multi-tenant нет.

---

## 2. UX/UI АУДИТ

Положительные стороны: единый `emoji_config.py` (plain Unicode в кнопках/alerts, premium `<tg-emoji>` в HTML-тексте), явная дифференциация `parse_mode="HTML"` vs plain, кнопка «В меню/Назад» на каждом экране (нет dead-end), paywall с одним CTA «Подключить за N ₽», авто-онбординг из 3 шагов, честное отсутствие автосписаний.

### UX-1 (Low, FIXED-частично) — Литеральный текст `{P.CHECK}` / `{P.CROSS}` в настройках
- **Файл:** `bot/handlers/settings_handler.py:234`
- **Шаги:** `/settings` → «Фильтры» (legacy) → смотрим строку «Авто-режим».
- **Ожидаемый:** `Авто-режим: ✅` / `❌`.
- **Фактический:** отображается `Авто-режим: {P.CHECK}` (буквально с фигурными скобками) — f-string `'{P.CHECK}' if ... else '{P.CROSS}'` трактуется как литерал (внутренние скобки экранированы).
- **Рекомендация:** `status = P.CHECK if profile.auto_mode_enabled else P.CROSS` затем `f"{P.ROBOT} Авто-режим: {status}"`. Добавить assertion в тест рендера.
- **Критичность:** Low (косметика legacy-экрана). **Из runtime-аудита НЕ исправлено.**

### UX-2 (Medium) — Долгая AI-операция без таймаута/отмены
- «✍️ Отклик»/«🔁 Ещё вариант»/«🧩 Кейсы» вызывают LLM синхронно в обработчике callback.
- Пользователь видит `query.answer("Готовлю отклик…")`, но если OpenRouter отвечает >10–30с, кнопка «залипает», отменить нельзя. Фолбэк на template при `LLMError` есть.
- **Рекомендация:** вынести генерацию в short async task + статусное сообщение, которое редактируется по готовности; дать кнопку «Отменить».
- **Файлы:** `proposals.py:99-148, 151-195, 331-384`.

### UX-3 (Low) — Нет подтверждения удаления источника
- `source_delete` удаляет соединение сразу без confirm-шага (`sources.py:178-186`). Случайный тап теряет канал/биржу. Нет undo.
- **Рекомендация:** второй callback `v2s:del:<id>:confirm` с «Точно удалить? Да/Нет».

### UX-4 (Low) — Onboarding не сохраняет прогресс при сбое
- `pending(context)` хранит `v2_onb_rate/tax` в `user_data`; между шагами введённые данные в БД ещё не сохранены (только в финале `onboarding_skills`). При рестарте без persistence промежуточные шаги теряются.
- **Рекомендация:** сохранять rate/tax инкрементально после каждого шага.

### UX-5 (Low) — Дублирующие элементы в paywall
- `deny_no_access` одновременно шлёт alert и отдельное сообщение с кнопкой оплаты (осознанный выбор), но для callback-нажатий генерирует 2 визуальных элемента. Приемлемо, но стоит A/B-проверить.


---

## 3. БИЗНЕС-ЛОГИКА

### BL-1 (Critical, FIXED) — Lost update при двух разных платежах
- **Пред. аудит:** `core/billing.py:117-126` читал `subscription_expires_at` без блокировки → два параллельных платежа с разными charge_id теряли 30 дней.
- **Текущее:** **ИСПРАВЛЕНО.** `apply_paid_subscription` делает `select(User).with_for_update().execution_options(populate_existing=True)` перед расчётом `period_end` (`billing.py:128-135`), вставка подписки и апдейт пользователя в одной транзакции с savepoint-recovery по `IntegrityError` на `payment_charge_id` (`billing.py:155-181`). Идемпотентность по charge_id сохранена.
- **Остаточный риск:** `with_for_update` требует PostgreSQL; на SQLite блокировка NO-OP (но в проде теперь PostgreSQL — см. BL-3). Нужен live PostgreSQL-конкурентный тест (в юнит-тестах SQLite эмулируется, но не доказывает межпроцессную атомарность).

### BL-2 (High, FIXED) — Неатомарный claim напоминания
- **Пред. аудит:** оба worker видели PENDING, оба коммитили NOTIFIED → двойная отправка.
- **Текущее:** **ИСПРАВЛЕНО.** `_claim_due_reminder` делает `select(Reminder).where(id, status==PENDING).with_for_update(skip_locked=True)` (`worker.py:601-611`); если строка захвачена/изменена — возвращает `None`, send пропускается. Статус коммитится ДО отправки (at-most-once: crash теряет ≤1 пинг, но не дублирует — §3.8). Аналогично outbox-доставка `_deliver_analysis_notification` использует `with_for_update(skip_locked=True)` + recovery stale `SENDING` (`worker.py:351-412, 415-460`).
- **Остаток:** live PostgreSQL-параллельный тест двух сессий пока отсутствует.

### BL-3 (High, FIXED) — Production Docker по умолчанию на SQLite
- **Пред. аудит:** `docker-compose.yml:18-19` безусловно переопределял `DATABASE_URL=sqlite...`.
- **Текущее:** **ИСПРАВЛЕНО.** `docker-compose.yml` поднимает `postgres:16-alpine` с healthcheck `pg_isready`, сервис `bot` ставит `DATABASE_URL=postgresql+asyncpg://...`, `depends_on.postgres.condition: service_healthy`, `RADAR_V2_ENABLED: "true"`, `ENVIRONMENT: production`. `scripts/entrypoint.sh` жёстко требует PostgreSQL в production (exit 64 иначе) и прогоняет `alembic upgrade head`.

### BL-4 (Medium, FIXED) — Reminder callback cross-tenant
- **Пред. runtime-аудит:** `reminder_write` проверял только `client.user_id`, но не `reminder.client_id == client.id`.
- **Текущее:** **ИСПРАВЛЕНО.** `crm_handlers.py:213-218` проверяет `reminder.client_id != client.id` в предикате; паттерн `v2r:write:<reminder_id>:<client_id>` безопасен. `reminder_snooze` грузит client через `reminder.client_id` и тоже проверяет `client.user_id`.

### BL-5 (Medium, FIXED) — TG-channel duplicate/limit race
- **Пред. аудит:** проверка лимита/дубликата только при тапе, обходилась задержкой текста.

### BL-6 (Medium, PARTIALLY) — Project callback IDs без tenant-авторизации
- **Пред. runtime-аудит:** `proposal_generate`/`proposal_cases` грузят `Project` по глобальному id без проверки, что проект виден пользователю.
- **Текущее:** **НЕ ИСПРАВЛЕНО.** `proposals.py:114` и `proposals.py:347` по-прежнему `project = await session.get(Project, project_id)`. `_latest_analysis` скопирован по `(project_id, user_id)`, так что чужой анализ недоступен, и `Proposal.user_id` защищает edit/regen/send. Однако **заголовок/описание чужого проекта раскрываются** в сгенерированной карточке/кейсах, если пользователь угадает `project_id`.
- **Оценка:** Projects — глобальная сущность (collector вставляет их без user_id, соответствует спеке §5). Но «видимость» проекта пользователем логически определяется тем, что его connection его доставил (через `NotificationDelivery`). Отсутствие связи «project виден пользователю» = IDOR-класс информационного раскрытия.
- **Критичность:** Medium. **Рекомендация:** перед генерацией/кейсами проверить существование `NotificationDelivery`/`ProjectAnalysis` для `(project_id, user_id)`, либо подгружать проект через join `Project.source_connection_id → ExchangeConnection.user_id == user.id`. Добавить forged-foreign-project тест.

### BL-7 (Medium) — `proposal_hide` без авторизации
- **Пред. runtime-аудит:** `proposal_hide` игнорирует callback-данные и удаляет любое сообщение с совпадающим `v2p:hide:<id>`.
- **Текущее:** **НЕ ИСПРАВЛЕНО.** `proposals.py:320-328` не проверяет `effective_user`/подписку/видимость — просто `query.answer` + `delete`. Скорее целостность/UI, чем утечка, но позволяет не-подписчику/истёкшему выполнить действие.
- **Критичность:** Medium (impact снижен, т.к. действие локальное). **Рекомендация:** проверить `effective_user` и парсить id; либо задокументировать hide как чисто-локальный UI.

### BL-8 (Low) — `/grant` без блокировки строки
- `grant_subscription` (`subscription.py:178-204`) напрямую ставит `subscription_tier/expires_at` без `with_for_update` и без `payment_charge_id`-идемпотентности. Owner-only, но два параллельных `/grant` одному пользователю теряют дни (аналогично BL-1 до фикса).
- **Рекомендация:** переиспользовать `apply_paid_subscription` с синтетическим charge_id (`manual:<timestamp>`) или `SELECT FOR UPDATE`.
- **Критичность:** Low (админ-команда, одиночный оператор).

### BL-9 (Low) — Trial создаётся при первом касании без подтверждения онбординга
- `get_or_create_user` сразу выдаёт `TRIAL` + 7 дней (`common.py:121-130`). Если пользователь случайно тапнул `/start`, триал уже тикает. Спека §7 «первые 7 дней бесплатно» — допустимо, но старт триала логичнее привязать к завершению онбординга.
- **Критичность:** Low (продуктовое решение).

### BL-10 (Low) — Tariff-gate неполнота

---

## 4. БЕЗОПАСНОСТЬ

### S-1 (Fixed, см. BL-4) — Cross-tenant reminder completion
Закрыто (`crm_handlers.py:213-218`). **Остаток:** нет regression-теста на mismatched `reminder_id` + caller-owned `client_id`.

### S-2 (Medium, см. BL-6) — IDOR project callbacks
`proposal_generate`/`proposal_cases` грузят глобальный `Project` без visibility-проверки → раскрытие title/description чужого заказа. Нет forged-foreign-project тестов.

### S-3 (Medium, см. BL-7) — `proposal_hide` без авторизации.

### S-4 (Low) — Global error handler: traceback есть, но нет user-recovery
- **Пред. runtime-аудит:** `main.py:117-122` логировал только `str(error)`, без traceback и без ответа пользователю.
- **Текущее:** **ИСПРАВЛЕНО частично.** `_telegram_error_handler` (`main.py:154-170`) теперь пишет `exc_info=context.error` (traceback в лог) и метаданные `update_id/telegram_user_id/chat_id` без содержимого апдейта (секреты не протекают). Но **user-facing recovery по-прежнему нет** — пользователь не получает уведомления об ошибке; NetworkError → warning, остальные → error. Безопасно, но UX-провал тихий.
- **Рекомендация:** best-effort `reply_text("Произошла ошибка, попробуйте ещё раз")` для message-originated обновлений.

### S-5 (Low) — `/grant` принимает любой `tier` кроме TRIAL
- `grant_subscription` разрешает `basic|pro|business`. С учётом решения «один тариф» безвредно (все = 300₽, legacy BASIC-лимиты сохранены). Но технически владелец может выдать BASIC с лимитами (50 анализов/мес, нет AI) — это поведение, а не уязвимость.

### S-6 (Info) — Секреты: гигиена корректна
- `.gitignore` покрывает `.env`, `*.session`, `*.db`, `*.zip`, `data/`, `logs/`, `.railway/`, `промпт на проверку.md`. Трекается только `freelance_radar.db` (legacy, см. S-7).
- `.env.example` — только плейсхолдеры, реальные ключи отсутствуют.
- `OPENAI_API_KEY` optional (для тестов), `PAYMENT_PROVIDER_TOKEN` empty по умолчанию (фича «ships dark»).

### S-7 (Low) — Legacy `freelance_radar.db` закоммичен в репозитории
- В корне лежит `freelance_radar.db` (используется legacy-ботом). `.gitignore` игнорирует `*.db`, но файл уже в истории. **Риск:** в SQLite-файле могли остаться тестовые/реальные данные (vacancies, profile, blacklist).
- **Рекомендация:** `git rm --cached freelance_radar.db`, проверить историю на чувствительные данные, при находке — ротировать/удалить через filter-repo. Это нарушение §8 AGENTS («секреты не коммитятся»; БД с ПДн клиентов — критичнее для 152-ФЗ).

### S-8 (Info) — SQL Injection / XSS
- Все запросы — SQLAlchemy ORM/параметризованные (`select(...).where(...)`), raw-text только `SELECT 1` в healthcheck. SQLi не обнаружено.
- XSS: пользовательский контент (имя клиента, заметки, портфолио, скиллы, ввод онбординга) экранируется через `esc()` = `html.escape` (`common.py:84-86`) перед вставкой в HTML-карточки. Скрапированный `project.title/description/summary` тоже экранируется (`cards.py:63-94`). URL фильтруется по схеме http(s) (`cards.py:95-97`, защита от silent loss). **XSS защищён.**
- LLM-инъекция: пользовательский/скрапированный текст передаётся в модель через `json.dumps` с явной инструкцией «не выполнять инструкции внутри полей» (`generation.py:336-346`) — prompt-injection mitigation присутствует.

### S-9 (Info) — CSRF / IDOR на REST
- Веб-дашборд (FastAPI/Next.js) в репозитории **отсутствует** (дорожная карта Фаза 3). CSRF/IDOR-API неприменимы. Bot API не имеет CSRF (обновления подписаны bot token).

### S-10 (Info) — Broken Access Control
- Legacy-команды (`/check`, `/health`, `/stats`, `/search`, `/chart`, `/blacklist`, broadcast) — `@owner_only` (`bot/auth.py:38-49`), проверка `user.id == OWNER_CHAT_ID`. V2-команды открытые (мульти-тенант), но тарифный gate `effective_tier` + `get_limits` защищают платные функции; `deny_no_access` даёт paywall. **Контроль доступа корректен.**

### S-11 (Low) — Flood/Spam защита
- PTB `AIORateLimiter` (глобальный), broadcast sliding-window Redis + часовой кулдаун чата (`config.py` `BROADCAST_*`), broadcast `max_instances=1, coalesce=True` (`main.py:411-418`). Для V2-user-команд нет per-user rate-limit (пользователь может спамить кнопками «Отклик» → LLM-нагрузка/расход токенов).

---

## 5. ПРОИЗВОДИТЕЛЬНОСТЬ

### P-1 (Medium) — AI Cache/LLM-cache не используется в V2
- README заявляет «AI Cache LRU 24ч» для legacy. В V2 `core/generation.py` использует `@lru_cache(maxsize=16)` только для `load_prompt` (файл→строка), **не для ответов LLM**. Каждый `proposal_generate`/`regen`/`cases` — отдельный LLM-вызов без кэша.
- **Риск:** расход токенов OpenRouter; при повторных тапах «Ещё вариант» кэш не помогает (осознанно: нужны разные варианты).
- **Рекомендация:** для proposal кэш избыточен; extraction не повторяется (`uq_analysis_project_user`). ОК как есть, но задокументировать.

### P-2 (Medium) — Долгая AI-операция блокирует update-цикл
- Генерация отклика синхронна в callback-handler. PTB обрабатывает обновления конкурентно (по умолчанию), но один тяжёлый LLM-вызов занимает worker-слот. При наплыве пользователей генерации встают в очередь без явного backpressure.
- **Рекомендация:** вынести в отдельную asyncio-task + статусное сообщение (как в UX-2).

### P-3 (Low) — Weekly report: N+1 запросов
- `run_weekly_report_tick` (`worker.py:692-733`) в цикле по всем пользователям делает 3 отдельных запроса на пользователя (analyses, proposals, active_clients). При росте базы → линейный рост запросов.
- **Рекомендация:** агрегирующий запрос с GROUP BY по user_id.

### P-4 (Low) — `run_radar_tick` читает всех users/connections одним проходом
- Известная staleness-окно задокументировано (`worker.py:493-496`). Приемлемо для MVP-масштаба.

### P-5 (Info) — Network I/O вне транзакции
- Транзакционный дизайн корректен: scrape/LLM/Telegram вне открытой DB-сессии, короткие tx на collect/analyze, notify после commit. Это устраняет основную узкую точку блокировок.

### P-6 (Low) — Batch DB-операции
- Collector использует savepoint-per-insert (`collector.py:161-172`), не bulk. При большом числе новых листингов — N вставок вместо 1 batch. Приемлемо (новых за тик мало).

---

## 6. SEO
**Неприменимо.** Проект — Telegram-бот, публичного сайта/лендинга в репозитории нет (веб-дашборд — Фаза 3, код отсутствует). Раздел пропускается.

---

## 7. TELEGRAM BOT

### T-1 (Info, корректно) — Все команды/FSM/ConversationHandler
- Команды: `/start /radar /menu /portfolio /clients /subscription /help /grant /broadcast /check /health /stats /search /chart /blacklist`. Зарегистрированы в `main.py` и V2 `register_v2_handlers`.
- FSM: onboarding (RATE→TAX→SKILLS), portfolio (P_TITLE→P_DESC→P_TAGS), broadcast (10 состояний). Все с `/cancel` fallback.
- ВНИМАНИЕ: PTB-предупреждение `per_message=False` в `ConversationHandler` (видно в warnings тестов) — для callback-driven conversations надо `per_message=True`, иначе нажатия кнопок могут не трекаться. Это warning, не error, но стоит проверить поведение в проде.

### T-2 (Fixed) — Обработка ошибок
- `_telegram_error_handler` ловит все исключения, логирует с `exc_info` (см. S-4). NetworkError → warning, прочее → error. Не падает.

### T-3 (Low) — Некорректный ввод: валидация есть, но не везде единообразна
- Onboarding: `int()` в try/except с диапазоном — хорошо. Tax: `float()` с запятой/процентом — хорошо. Skills: split+truncate 30 — хорошо.
- Channel: проверка `len(username) < 4` и `@`-префикс — хорошо.
- Portfolio: truncation `[:200]/[:1500]` без валидации содержимого (HTML/emoji экранируются при рендере) — приемлемо.
- **Gap:** проверить длину заметок CRM (`apply_client_note`).

### T-4 (Medium) — Конкурентные действия пользователя
- `get_or_create_user` — concurrency-safe через `IntegrityError` recovery (`common.py:121-135`). Хорошо.
- `add_channel_from_text` — `with_for_update` + unique constraint. Хорошо.
- **Gap:** `proposal_generate` создаёт `Proposal` без unique guard — повторный быстрый тап «Отклик» (double-tap) создаст 2 черновика. Есть double-tap-тесты в `test_v2_audit_fixes.py`, но для proposal-draft дубликата — проверить.

### T-5 (Low) — Перезапуск бота / потеря состояния
- PicklePersistence подключён (`main.py` — V2 `persistent=persistent`). Redis для FSM заявлен (`.env.example REDIS_URL`), но `PTB_STATE_DIR=/app/data` (PicklePersistence на диск). На multi-replica (`BOT_REPLICAS>1`) pickle-файл НЕ разделяется между репликами → FSM-состояние теряется при балансировке на другую реплику.
- **Рекомендация:** для `BOT_REPLICAS>1` обязателен Redis-backed `PicklePersistence`/`DictPersistence` или явное требование `BOT_REPLICAS=1` в проде.

### T-6 (Low) — Защита от флуда

---

## 8. EDGE CASES

### E-1 (Fixed-частично) — Пустой/whitespace ввод TG-канала
- **Пред.** runtime-аудит: `text.strip().split()[0]` → IndexError. **Текущее:** `if not parts` guard (`sources.py:200-205`) — починено, но **FSM-состояние `v2_add_channel` всё ещё `pop`-ается в router** (`router.py:27`) до вызова `add_channel_from_text`, поэтому при ошибке валидации следующее сообщение пользователя игнорируется (flow потерян). Это остаток runtime-аудита «pending state lost on validation error».
- **Критичность:** Low/Medium. **Рекомендация:** в `router.py` использовать `.get()` вместо `.pop()` для `v2_add_channel` и заново `set` его при ошибке валидации, либо перевести на ConversationHandler.

### E-2 (Info) — Очень длинный ввод
- Onboarding rate/tax: `int/float` усекаются/валидируются диапазоном. Skills: `[:30]` после split. Portfolio: `[:200]/[:1500]`. Channel: `split()[0]`. Поиск: `[:200]`. **Длинный ввод обрезается — ОК.**
- **Gap:** `apply_client_note` (CRM заметка) — проверить truncation.

### E-3 (Info) — Спецсимволы/Emoji/HTML/SQL/JS/Unicode
- Всё пользовательское сохраняется как есть (JSON-колонки / Text) и экранируется `html.escape` при рендере. SQL-команды как текст — безопасно (ORM). JS/HTML в полях — экранируются, не выполняются. Emoji — сохраняются и отображаются. Unicode (RTL, ZWJ) — сохраняется. **Защищено.**
- **Единственный риск:** Telegram `parse_mode="Markdown"` в legacy (`commands.py:309,323,327`) с пользовательским запросом `query` в `f"по запросу '{query}'"` — Markdown-инъекция (пользователь вводит `*`/`_`/`` ` `` → ломает разметку). Не XSS (Markdown V1 не выполняет JS), но визуальный мусор. **Рекомендация:** экранировать `query` для Markdown или использовать HTML.

### E-4 (Low) — Повторные/массовые запросы
- Outbox `with_for_update(skip_locked=True)` + unique constraints защищают от дублей. `Proposal` — см. T-4. Broadcast — `max_instances=1, coalesce=True`. **В целом защищено.**

---

## 9. АВТОМАТИЧЕСКИЙ ПОИСК БАГОВ

### B-1 (Low) — `save_group_name` переменная `name` при пустом message.text
- `broadcast_handler.py:126`: `name = (update.message.text or "").strip()` — если `update.message.text is None` (фото/стикер), `name = ""`, проверка `1 <= 0 <= 100` → False → повтор. Корректно, но стоит явно `if not update.message.text: return ENTERING_GROUP_NAME`.

### B-2 (Info) — Неконсистентность legacy vs V2 БД
- Legacy (`freelance_radar.db`, aiosqlite) и V2 (SQLAlchemy/PostgreSQL) — две раздельные БД. `db/init_db.py` инициализирует legacy, `alembic` — V2. В V2-режиме обе живые, но данные не синхронизированы (поиск `/search` — по legacy, заказы — в V2). Архитектурный долг, задокументирован в `docs/V2_IMPLEMENTATION.md`.

### B-3 (Info) — `_telegram_error_handler` подписан на `object` update
- Сигнатура `(update: object, context)` — PTB передаёт реальный `Update`; `getattr`-доступ безопасен. ОК.

### B-4 (Info) — Логирование
- `structlog` через `get_logger`, структурированные поля, sensitive-данные (update text) не логируются в error-handler. Хорошие практики. `billing.duplicate_charge_ignored` логирует `charge_id` (не секрет). ОК.

### B-5 (Fixed) — N× extraction cost

---

## 10. ИТОГОВЫЙ ОТЧЁТ

### Критические проблемы
- **Критических блокеров не выявлено.** Все 3 HIGH из предыдущего аудита (BL-1/BL-2/BL-3) **исправлены** в данной ветке (`with_for_update`, `skip_locked`, PostgreSQL по умолчанию).
- **Остаточный критический риск (операционный, не кодовый):** отсутствие live PostgreSQL concurrency-тестов (BL-1/BL-2 доказаны только на SQLite-эмуляции) и отсутствие backup/restore-процедур для production multi-tenant БД с ПДн клиентов (152-ФЗ).

### Высокий приоритет
1. **BL-6 / S-2** — IDOR project callbacks: `proposal_generate`/`proposal_cases` грузят глобальный `Project` без проверки видимости пользователем → раскрытие title/description чужого заказа. **Файл:** `bot/handlers/v2/proposals.py:114, 347`.
2. **T-5 / S-multi-replica** — `BOT_REPLICAS>1` + PicklePersistence на диске → потеря FSM-состояния между репликами; нужен Redis-state или фиксация `BOT_REPLICAS=1`.
3. **S-7** — `freelance_radar.db` закоммичен в git-истории (возможные ПДн); `git rm --cached` + аудит истории.

### Средний приоритет
4. **BL-7 / S-3** — `proposal_hide` без авторизации (`proposals.py:320-328`).
5. **E-1 / UX** — pending-state `v2_add_channel` теряется при ошибке валидации (`router.py:27` pop вместо get).
6. **UX-2 / P-2** — AI-генерация синхронна в callback, без отмены/таймаута/статусного сообщения.
7. **BL-8** — `/grant` без блокировки строки (двойной grant теряет дни).
8. **P-3** — weekly report N+1 запросов по пользователям.
9. **T-4** — `proposal_generate` без guard от double-tap → 2 черновика.
10. **S-11 / T-6** — нет per-user rate-limit на V2 AI-команды (расход токенов при спаме).

### Низкий приоритет
11. **UX-1** — литерал `{P.CHECK}`/`{P.CROSS}` в `settings_handler.py:234` (из runtime-аудита НЕ починено).
12. **S-4** — error-handler без user-facing recovery (only log).
13. **UX-3** — нет подтверждения удаления источника.
14. **UX-4** — onboarding не сохраняет прогресс инкрементально.
15. **F-1** — V2 не имеет браузера/поиска по проектам.
16. **F-2** — legacy-фильтры недоступны в V2.
17. **E-3** — Markdown-инъекция в legacy `/search` (`commands.py:327`).
18. **BL-9** — trial стартует при первом касании, а не после онбординга.
19. **B-1** — `save_group_name` edge с пустым message.text.
20. **B-2** — legacy/V2 БД-рассинхронизация (долг).

### UX рекомендации
- Сделать status-сообщение для AI-операций с кнопкой «Отменить» (UX-2).
- Добавить confirm-шаг для деструктивных действий (UX-3).
- Сохранять прогресс онбординга пошагово (UX-4).
- Починить литерал `{P.CHECK}` (UX-1).
- Добавить раздел «Мои заказы/Архив» с пагинацией и фильтром по скорингу (F-1).
- Показывать явно «шаблон» vs «AI» в кнопке/карточке отклика (BL-10).

### Безопасность
- Закрыть IDOR project callbacks (BL-6): visibility-проверка через `NotificationDelivery`/`ProjectAnalysis` или join по `source_connection_id → ExchangeConnection.user_id`.
- Добавить авторизацию в `proposal_hide` (BL-7).
- `git rm --cached freelance_radar.db` + аудит истории на ПДн (S-7).
- Перевести pending-channel-flow на `get` вместо `pop` (E-1).
- Per-user cooldown на AI-команды (S-11).
- Добавить regression-тесты: mismatched reminder/client, forged foreign-project, blank channel input, double-tap proposal.

### Производительность
- Вынести AI-генерацию в asyncio-task (P-2).
- Агрегировать weekly-report одним GROUP BY (P-3).
- Batch-insert в collector при росте листингов (P-6).

### Общая оценка проекта

| Критерий | Оценка | Обоснование |
|---|---|---|
| Функциональность | **8/10** | Все заявленные MVP-функции реализованы и протестированы; недостаёт браузера/поиска V2-проектов и ручных фильтров в multi-tenant. |
| UX/UI | **7/10** | Единый эмодзи-слой, нет dead-end, честный paywall; но AI-операции без прогресса/отмены, литерал-баг в настройках, нет confirm-удаления. |
| Безопасность | **7.5/10** | ORM/экранирование/rate-limit/секреты — корректно; но остаточный IDOR project callbacks, hide без авторизации, закоммиченная БД, нет per-user flood-control. Все 3 прежних HIGH закрыты. |
| Производительность | **8/10** | Транзакционный дизайн корректен; вынести синхронные LLM-вызовы и оптимизировать weekly N+1. |
| Готовность к запуску | **7/10** | Тесты зелёные (462), lint/type зелёные, Docker/PostgreSQL/healthcheck готовы; но **нельзя пускать в прод multi-replica без Redis-state**, **без backup/restore** и **без закрытия IDOR**. Для single-replica + PostgreSQL + после фиксов BL-6/BL-7/S-7 — готов к ограниченному запуску. |

### ТОП-20 улучшений (по приоритету)

1. **(High)** Закрыть IDOR project callbacks: проверять видимость проекта в `proposal_generate`/`proposal_cases` (`proposals.py:114,347`).
2. **(High)** Зафиксировать `BOT_REPLICAS=1` или подключить Redis-backed FSM-state для multi-replica.
3. **(High)** `git rm --cached freelance_radar.db` + аудит git-истории на ПДн, при находке — удалить через filter-repo (152-ФЗ).
4. **(Medium)** Добавить авторизацию в `proposal_hide` (`proposals.py:320-328`).
5. **(Medium)** Перевести `v2_add_channel` pending-state на `get`/re-set при ошибке валидации (`router.py:27`).
6. **(Medium)** Вынести AI-генерацию отклика в asyncio-task со статусным сообщением и кнопкой «Отменить».
7. **(Medium)** `/grant` — переиспользовать `apply_paid_subscription` с синтетическим charge_id или `FOR UPDATE`.
8. **(Medium)** Добавить live PostgreSQL concurrency-тест для `apply_paid_subscription` и `_claim_due_reminder` (две сессии + барьер).
9. **(Medium)** Per-user cooldown на AI-команды (proposal generate/regen/cases).
10. **(Medium)** Aggregating `GROUP BY user_id` для weekly report (`worker.py:692-733`).
11. **(Low)** Починить литерал `{P.CHECK}`/`{P.CROSS}` в `settings_handler.py:234`.
12. **(Low)** Confirm-шаг для удаления источника (`sources.py`).
13. **(Low)** Инкрементальное сохранение прогресса онбординга.
14. **(Low)** Добавить regression-тесты: mismatched reminder/client, forged foreign-project, blank channel input, double-tap proposal draft.
15. **(Low)** Раздел «Мои заказы/Архив» в V2 с пагинацией/фильтром по скорингу.
16. **(Low)** Best-effort user-facing recovery в `_telegram_error_handler`.
17. **(Low)** Экранировать пользовательский `query` в legacy `/search` (Markdown-инъекция).
18. **(Low)** Привязать старт trial к завершению онбординга, а не к первому касанию.
19. **(Low)** Документировать backup/restore + data-retention runbook для production PostgreSQL.
20. **(Low)** Batch-insert в `Collector.collect` при росте числа новых листингов.

---

## Резюме

Проект **сильно продвинулся** с момента предыдущих аудитов: все три HIGH-блокера
(конкурентные платежи, неатомарный claim напоминаний, SQLite-по-умолчанию в проде)
**исправлены и подкреплены тестами**. Транзакционный дизайн worker'а вынесен в
best-practice (network I/O вне транзакций, `with_for_update(skip_locked=True)` для outbox
и reminders, savepoint-per-insert в collector, идемпотентность по unique-constraints).

Кодовая гигиена высокая: ruff/mypy зелёные на типизированном V2-слое, `esc()`-экранирование
везде, секреты не коммитятся, prompts версионируются файлами, LLM-инъекция митигирована.

До production-запуска остаются **3 высокоприоритетные** задачи (IDOR project callbacks,
multi-replica FSM-state, удаление закоммиченной БД) и ~7 средних. После их закрытия
проект готов к ограниченному запуску (single-replica, PostgreSQL, с backup-runbook).