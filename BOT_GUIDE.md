# FreelanceRadar Bot — Полное руководство от А до Я

## 1. Что это за бот

**FreelanceRadar** — Telegram-бот для автоматического мониторинга фриланс-бирж (Kwork) и Telegram-каналов с вакансиями. Бот:

- Парсит вакансии с источников
- Анализирует их через OpenAI GPT (приоритет, score, риски)
- Фильтрует по твоему профилю и настройкам
- Отправляет подходящие вакансии в Telegram
- Генерирует готовые отклики
- Поддерживает авто-режим для high-priority вакансий

---

## 2. Архитектура (общая схема)

```
┌─────────────────┐
│   Telegram API  │ ←←← Пользователь взаимодействует с ботом
└────────┬────────┘
         │
┌────────▼────────┐     ┌──────────────────┐
│   main.py       │────▶│  python-telegram │
│  (entry point)  │     │     -bot v20     │
└────────┬────────┘     └──────────────────┘
         │
    ┌────┴────┐
    │         │
┌───▼───┐ ┌──▼────┐
│Commands│ │Handlers│ ← /start, /check, кнопки меню
└───┬───┘ └──┬────┘
    │        │
┌───▼────────▼────┐
│  services/      │
│  scheduler.py   │ ← Основной цикл проверки (каждые 15 мин)
└───┬─────────────┘
    │
    │ 1. Fetch
┌───▼─────────────┐
│  services/      │
│  monitor.py     │ ← Запрашивает парсеры
└───┬─────────────┘
    │
    ├──────────────┬──────────────┐
    │              │              │
┌───▼────┐   ┌────▼────┐   ┌────▼────┐
│parsers/│   │parsers/ │   │   DB    │
│ kwork  │   │telegram │   │ SQLite  │
│.py     │   │_source  │   │         │
└────────┘   │.py      │   └─────────┘
             └─────────┘
    │
    │ 2. Filter
┌───▼─────────────┐
│ services/       │
│ filters.py      │ ← Pre-filter + Post-filter
└───┬─────────────┘
    │
    │ 3. Analyze (AI)
┌───▼─────────────┐
│ services/       │
│ job_analyzer.py │ ← OpenAI GPT-4o-mini
└───┬─────────────┘
    │
    │ 4. Generate response
┌───▼─────────────┐
│ services/       │
│response_generator│ ← OpenAI GPT-4o-mini
└───┬─────────────┘
    │
    │ 5. Notify
┌───▼─────────────┐
│ services/       │
│ notifications.py│ ← Отправка в Telegram
└─────────────────┘
```

---

## 3. Компоненты подробно

### 3.1 main.py — точка входа

**Что делает:**
1. Инициализирует логирование (`structlog`)
2. Валидирует конфигурацию (проверяет `.env`)
3. Запускает миграции БД (`init_and_migrate()`)
4. Регистрирует все Telegram handlers (команды, кнопки)
5. Запускает `APScheduler` для периодических задач:
   - `check_sources` — каждые 15 минут (проверка вакансий)
   - `health_check` — каждые 30 минут (проверка здоровья)
   - `cleanup_blacklist` — каждый час (очистка чёрного списка)
6. Запускает `application.run_polling()` — бот слушает сообщения

**Ключевые handlers:**
- `/start` — приветствие + главное меню
- `/check` — ручной запуск проверки
- `/health` — статус системы
- `/stats` — статистика вакансий
- `/blacklist` — управление чёрным списком
- `/search` — поиск по вакансиям (FTS5)
- `/chart` — графики статистики

### 3.2 config.py — конфигурация

Использует **Pydantic Settings** для валидации переменных окружения из `.env`.

**Обязательные поля:**
```bash
BOT_TOKEN=your_bot_token          # Токен от @BotFather
OWNER_CHAT_ID=123456789           # Твой Telegram ID (число)
OPENAI_API_KEY=sk-...             # API ключ OpenAI
```

**Опциональные поля:**
```bash
DB_PATH=freelance_radar.db        # Путь к SQLite
MONITOR_INTERVAL_MINUTES=15       # Интервал проверки
KWORK_MAX_DETAIL_PAGES=5          # Сколько детальных страниц парсить
DEFAULT_COOLDOWN_SEC=3600         # Кулдаун на отправку сообщений
```

### 3.3 Парсеры

#### parsers/kwork.py — Kwork парсер
- Использует **Playwright** (браузерная автоматизация)
- Заходит на `https://kwork.ru/projects`
- Блокирует ненужные ресурсы (CSS, шрифты) для скорости
- Парсит карточки проектов
- Для первых 5 проектов заходит на детальные страницы
- Извлекает: заголовок, описание, бюджет, сроки, рейтинг заказчика

#### parsers/telegram_source.py — Telegram парсер
- **НЕ использует Telethon** (исправлено)
- Парсит `https://t.me/s/channel_name` (публичный веб-превью)
- Использует `httpx` + `BeautifulSoup4`
- Извлекает текст сообщений, хештеги, бюджет
- Не требует API ID/API HASH

### 3.4 services/scheduler.py — основной цикл

**Функция `check_and_notify_streaming()`:**

```python
Шаг 1: Fetch    → Получаем вакансии со всех источников
Шаг 2: Filter   → Pre-filter (бюджет, чёрный список, слова)
Шаг 3: Save     → Сохраняем новые вакансии в БД
Шаг 4: Analyze  → OpenAI анализирует каждую вакансию
Шаг 5: Post-filter → AI score, match percentage
Шаг 6: Notify   → Отправляем в Telegram
Шаг 7: Auto-mode → Генерируем отклики для high-priority
```

**Auto-mode (авторассылка):**
- Если в профиле включён `auto_mode_enabled`
- И вакансия имеет приоритет `high`
- Бот генерирует отклик через OpenAI
- Сохраняет отклик в БД
- Отправляет тебе уведомление с готовым текстом

### 3.5 services/job_analyzer.py — AI анализ

**Промпт для OpenAI просит оценить:**
- `score` — 0-100 (общая оценка)
- `priority` — low/medium/high
- `match_percentage` — совпадение с навыками
- `risks` — риски
- `complexity` — сложность
- `skills_required` — требуемые навыки

**Если OpenAI недоступен** — fallback scoring:
- Бюджет 50000+ → +30 баллов
- Срок 14+ дней → +15 баллов
- Рейтинг 4.0+ → +10 баллов
- Совпадение навыков → до +30 баллов

### 3.6 services/filters.py — фильтры

**Pre-filters (до AI):**
- Чёрный список (вакансии/заказчики)
- Бюджет (min/max из профиля)
- Чёрный список слов
- Белый список слов (хотя бы одно должно быть)
- Рейтинг заказчика
- Количество предложений

**Post-filters (после AI):**
- AI score < 50 — отфильтровываем
- Match percentage < 30 — отфильтровываем

### 3.7 services/response_generator.py — генерация откликов

- Использует OpenAI для написания отклика
- Учитывает профиль фрилансера (навыки, опыт, портфолио)
- Поддерживает custom prompt из настроек
- Если OpenAI недоступен — fallback template

### 3.8 db/ — база данных (SQLite)

**Таблицы:**

| Таблица | Назначение |
|---------|-----------|
| `vacancies` | Все вакансии (уникальность по kwork_id) |
| `sources` | Источники (Kwork, Telegram каналы) |
| `user_settings` | Настройки пользователя (промпты, бюджет) |
| `freelancer_profile` | Профиль фрилансера (навыки, фильтры) |
| `responses` | Сгенерированные отклики |
| `chat_cooldowns` | Кулдауны на отправку сообщений |
| `blacklist` | Чёрный список |
| `vacancies_fts` | FTS5 виртуальная таблица для полнотекстового поиска |

**Ключевые поля vacancies:**
- `kwork_id` — уникальный ID (STRING)
- `ai_score`, `ai_priority` — результаты AI анализа
- `filtered_out` — отфильтрована ли
- `responded` — был ли отклик

### 3.9 bot/handlers/ — обработчики

- **jobs_handler.py** — просмотр вакансий, пагинация, отклики
- **sources_handler.py** — управление источниками (добавление, удаление)
- **settings_handler.py** — настройки (промпты, фильтры, авто-режим)
- **profile_handler.py** — профиль фрилансера (навыки, опыт, ставка)
- **commands.py** — команды (/start, /check, /stats, /health, /search, /chart)

---

## 4. История ошибок и исправления

### Ошибка 1: `sqlite3.OperationalError: no such column: urls`

**Причина:** В таблице `sources` не было колонки `urls`. База была создана до того, как эта колонка была добавлена в схему.

**Исправление:**
1. В `db/init_db.py` миграция добавляет колонку `urls` если её нет
2. В `main.py` добавлен вызов `init_and_migrate()` перед стартом бота
3. Миграция была применена вручную через `python -c "from db.init_db import init_and_migrate; asyncio.run(init_and_migrate())"`

### Ошибка 2: `RuntimeError: Event loop is closed`

**Причина:** После `loop.run_until_complete(init_and_migrate())` я вызывал `loop.close()`, но APScheduler и `run_polling()` пытались использовать тот же loop.

**Исправление:** Убрал `loop.close()` из `main.py`.

### Ошибка 3: `sqlite3.IntegrityError: UNIQUE constraint failed: vacancies.kwork_id`

**Причина:** `batch_save_vacancies()` использовал `INSERT INTO`, что падает при попытке вставить уже существующий `kwork_id`.

**Исправление:** Заменил `INSERT INTO` на `INSERT OR IGNORE INTO` в:
- `save_vacancy()`
- `batch_save_vacancies()`

### Ошибка 4: `DeprecationWarning: There is no current event loop`

**Причина:** `asyncio.get_event_loop()` в Python 3.10+ deprecated когда нет текущего event loop.

**Исправление:** Заменил на `asyncio.new_event_loop()`.

### Ошибка 5: Telegram parser — `The API access for bot users is restricted`

**Причина:** `parsers/telegram_source.py` использовал Telethon с бот-токеном. Telethon требует пользовательский API (api_id/api_hash), а не бот-токен.

**Исправление:** Полностью переписал парсер:
- Убрал Telethon
- Теперь использует `httpx` + `BeautifulSoup` для парсинга `t.me/s/channel_name`
- `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` стали опциональными

### Ошибка 6: Shutdown errors `httpx.ReadError`, `HTTPXRequest is not initialized!`

**Причина:** При остановке бота (Ctrl+C) updater пытался получать updates уже после закрытия HTTP клиента.

**Исправление:**
- Добавил `application.add_error_handler(_telegram_error_handler)`
- В `_graceful_shutdown` убрал `await application.shutdown()` (только `stop()`)
- NetworkError теперь логируется как warning, не error

---

## 5. Как использовать бота

### Первый запуск

1. Создай `.env` файл:
```bash
BOT_TOKEN=your_bot_token_from_BotFather
OWNER_CHAT_ID=your_telegram_id
OPENAI_API_KEY=sk-your-openai-key
```

2. Установи зависимости:
```bash
pip install -r requirements.txt
```

3. Установи Playwright:
```bash
playwright install chromium
```

4. Запусти:
```bash
python main.py
```

### Настройка профиля

1. Нажми **👤 Профиль**
2. Заполни:
   - **Навыки** — через запятую (python, django, react)
   - **Опыт** — годы
   - **Ставка/час** — для фильтра бюджета
   - **Сильные стороны** — для генерации откликов
   - **Портфолио** — ссылка

### Настройка фильтров

1. Нажми **⚙️ Настройки → 🔍 Фильтры**
2. Настрой:
   - **Белый список слов** — вакансии должны содержать хотя бы одно
   - **Чёрный список слов** — вакансии с этими словами игнорируются
   - **Мин. рейтинг заказчика** — например, 4.0
   - **Макс. предложений** — например, 20

### Включение авто-режима

1. Нажми **⚙️ Настройки → 🔍 Фильтры → 🤖 Авто-режим**
2. Нажми **▶️ Включить авто-режим**
3. Настрой задержку (минут)

Теперь для всех **high priority** вакансий бот будет:
- Автоматически генерировать отклик
- Сохранять его в БД
- Отправлять тебе уведомление с готовым текстом

### Управление источниками

1. Нажми **📡 Источники**
2. **➕ Добавить источник**
3. Выбери тип:
   - **Kwork** — добавляется автоматически, URL не нужен
   - **Telegram канал** — введи `@channelname` или `https://t.me/channelname`

### Просмотр вакансий

1. Нажми **📋 Вакансии**
2. Вакансии показываются с пагинацией (5 на страницу)
3. Кнопки действий:
   - **💬 Отклик** — сгенерировать отклик
   - **🚀 Отправить** — показать готовый текст для копирования (high priority)
   - **👀 Подробнее** — детали вакансии
   - **⏳ Отложить** — пропустить
   - **🚫 В чёрный список** — заблокировать

---

## 6. Структура проекта

```
freelance-radar/
├── main.py                    # Точка входа
├── config.py                  # Конфигурация (.env)
├── constants.py               # Константы (Priority, FilterReason)
├── .env                       # Переменные окружения
├── requirements.txt           # Зависимости
│
├── bot/                       # Telegram бот
│   ├── auth.py               # Проверка прав (owner_only)
│   ├── commands.py           # Команды (/start, /check...)
│   ├── keyboards.py          # Клавиатуры
│   ├── middleware.py         # Middleware
│   └── handlers/             # Обработчики
│       ├── jobs_handler.py   # Вакансии
│       ├── sources_handler.py # Источники
│       ├── settings_handler.py # Настройки
│       └── profile_handler.py  # Профиль
│
├── db/                        # База данных
│   ├── models.py             # Dataclasses (JobVacancy, Source...)
│   ├── queries.py            # SQL запросы
│   ├── init_db.py            # Инициализация + миграции
│   └── database.py           # Connection manager
│
├── parsers/                   # Парсеры
│   ├── base.py               # Базовый класс
│   ├── kwork.py              # Kwork (Playwright)
│   ├── telegram_source.py    # Telegram (httpx + BS4)
│   └── utils.py              # Утилиты парсинга
│
├── services/                  # Бизнес-логика
│   ├── scheduler.py          # Основной цикл проверки
│   ├── monitor.py            # Мониторинг источников
│   ├── job_analyzer.py       # AI анализ (OpenAI)
│   ├── response_generator.py # Генерация откликов
│   ├── filters.py            # Фильтры вакансий
│   ├── notifications.py      # Отправка уведомлений
│   ├── sender.py             # Отправка сообщений
│   ├── formatters.py         # Форматирование текста
│   ├── blacklist.py          # Чёрный список
│   ├── ai_cache.py           # Кэш AI ответов
│   ├── metrics.py            # Метрики
│   ├── event_bus.py          # Шина событий
│   ├── logger_config.py      # Логирование
│   └── ...                   # Прочие сервисы
│
└── tests/                     # Тесты
    ├── unit/                 # Юнит-тесты
    └── integration/          # Интеграционные тесты
```

---

## 7. Ключевые технологии

| Компонент | Технология |
|-----------|-----------|
| Telegram Bot | `python-telegram-bot` v20.8 |
| HTTP запросы | `httpx` |
| Браузерная автоматизация | `playwright` |
| HTML парсинг | `beautifulsoup4` |
| AI | `openai` (GPT-4o-mini) |
| База данных | `aiosqlite` (SQLite async) |
| Полнотекстовый поиск | SQLite FTS5 |
| Периодические задачи | `APScheduler` |
| Логирование | `structlog` |
| Конфигурация | `pydantic-settings` |
| Retry / Circuit Breaker | `tenacity` |

---

## 8. Поток данных при проверке

```
1. APScheduler запускает scheduled_check()
   │
2. check_and_notify_streaming()
   ├── 2a. monitor.fetch_all_vacancies()
   │      ├── kwork_parser.fetch_vacancies() → 10 вакансий
   │      └── telegram_parser.fetch_messages_from_channel() → 0 вакансий
   │
   ├── 2b. get_seen_kwork_ids() → {уже виденные ID}
   │      Фильтруем дубликаты
   │
   ├── 2c. apply_pre_filters() → бюджет, чёрный список, слова
   │      Отфильтрованные → save_vacancy(filtered_out=True)
   │      Новые → save_vacancy()
   │
   ├── 2d. analyzer.analyze_jobs() → 5 параллельных запросов к OpenAI
   │      Получаем: score, priority, match_percentage...
   │
   ├── 2e. apply_post_filters() → score < 50 отфильтровываем
   │
   ├── 2f. notify_new_vacancy() → отправка в Telegram
   │      Каждая вакансия приходит отдельным сообщением
   │
   └── 2g. Auto-mode (если включен)
          ├── generate_response() → OpenAI пишет отклик
          ├── save_response() → сохраняем в БД
          └── send_message() → уведомляем владельца

3. Итоговая статистика отправляется в Telegram
```

---

## 9. Безопасность

- **owner_only** — все команды защищены, работают только для `OWNER_CHAT_ID`
- **Чёрный список** — можно блокировать вакансии и заказчиков
- **Кулдаун** — защита от спама при отправке сообщений
- **Rate limiting** — ограничение запросов к OpenAI (20 RPM)
- **Circuit breaker** — отключение OpenAI при серии ошибок

---

## 10. Полезные команды для разработки

```bash
# Запуск бота
python main.py

# Запуск миграций вручную
python -c "import asyncio; from db.init_db import init_and_migrate; asyncio.run(init_and_migrate())"

# Проверка структуры БД
sqlite3 freelance_radar.db ".schema"

# Просмотр логов
# Логи пишутся через structlog, формат JSON

# Запуск тестов
pytest tests/
```

---

## 11. Что делать при проблемах

| Проблема | Решение |
|----------|---------|
| Бот не запускается | Проверь `.env`, убедись что все переменные заданы |
| Kwork не парсит | Проверь интернет, возможно Kwork блокирует IP |
| OpenAI ошибки | Проверь API ключ, баланс, rate limits |
| Нет уведомлений | Проверь что источники включены (`/sources`) |
| Дубликаты вакансий | Нормально, `INSERT OR IGNORE` их пропускает |
| Бот не отвечает | Проверь `OWNER_CHAT_ID`, должен совпадать с твоим |

---

## 12. Дальнейшее развитие (идеи)

- [ ] Интеграция с другими биржами (FL.ru, Habr Freelance)
- [ ] Авто-ответы на Kwork через API (если появится)
- [ ] Уведомления о новых сообщениях от заказчиков
- [ ] Мобильное приложение
- [ ] Веб-интерфейс для управления
- [ ] ML-модель для оценки вместо OpenAI
- [ ] Интеграция с Trello/Notion для трекинга откликов
