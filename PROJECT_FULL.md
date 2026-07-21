# FreelanceRadar — Полное описание проекта (v2.0)

---

## 1. Что это за проект

**FreelanceRadar** — это Telegram-бот для автоматического мониторинга фриланс-бирж и вакансий, анализа заказов с помощью ИИ (OpenAI GPT / Ollama fallback) и полуавтоматической генерации откликов.

**Цель:** Один фрилансер управляет ботом через Telegram. Бот сам ищет новые вакансии на Kwork и в Telegram-каналах, фильтрует их двухуровневой системой, анализирует с помощью AI с учётом профиля фрилансера, уведомляет владельца и помогает сгенерировать и отправить отклик.

**Стадия:** MVP v2.0 (масштабное обновление с фильтрами, профилем, stealth-парсингом).

---

## 2. Полная функциональность

### 2.1 Мониторинг источников
- **Автоматическая проверка** каждые N минут (по умолчанию 15) через APScheduler
- **Ручная проверка** командой `/check`
- **Источники:**
  - **Kwork** — парсинг с полными деталями через Playwright (headless Chromium) с stealth-режимом
  - **Telegram-каналы/чаты** — чтение сообщений через Telethon (userbot)

### 2.2 Парсинг Kwork v2 (Stealth + Full Details)
- **Stealth-режим:**
  - Ротация User-Agent (4 разных)
  - Ротация viewport (4 размера)
  - Дополнительные HTTP-заголовки (Sec-Fetch, Accept-Language, DNT)
  - Случайные задержки между запросами (2-5 сек)
  - Локаль ru-RU, часовой пояс Europe/Moscow

- **Полный парсинг карточек:**
  - Переход на `https://kwork.ru/projects` через Playwright
  - Извлечение списка URL `/projects/{id}/view`
  - **Для каждой вакансии** — отдельный запрос на страницу с деталями:
    - `title` — заголовок заказа
    - `description` — полное описание (до 3000 символов)
    - `budget` — бюджет как текст
    - `budget_min`, `budget_max` — числовой диапазон
    - `deadline` — срок как текст
    - `deadline_days` — срок в днях
    - `category` — основная категория (из breadcrumbs)
    - `subcategory` — подкатегория
    - `skills` — требуемые навыки/теги (JSON список)
    - `proposals_count` — количество предложений
    - `customer_rating` — рейтинг заказчика
    - `customer_orders` — количество заказов у клиента

### 2.3 Парсинг Telegram-каналов v2
- Подключение через Telethon (userbot, не бот-токен)
- Чтение последних N сообщений из канала
- **Улучшенная конвертация сообщения в `JobVacancy`:**
  - `title` — первая строка (до 100 символов)
  - `description` — полный текст (до 2000 символов)
  - `budget` — извлечение по regex (руб, ₽, $, USD, EUR, €)
  - `budget_min`, `budget_max` — числовой диапазон
  - `deadline` — извлечение по regex (день/дня/дней/недел/месяц/час)
  - `deadline_days` — срок в днях
  - `category` — из хэштегов или ключевых слов
  - `skills` — хэштеги
  - `url` — ссылка на сообщение
  - `kwork_id` — MD5-хеш от `tg_{channel}_{message_id}`

### 2.4 Двухуровневая система фильтров

**Level 1 — Pre-filters** (до сохранения в БД и AI-анализа):
- Бюджет (min/max из настроек)
- Чёрный список слов (вакансия отклоняется, если содержит)
- Белый список слов (вакансия должна содержать хотя бы одно)
- Минимальный рейтинг заказчика
- Максимальное количество предложений
- Отфильтрованные вакансии сохраняются в БД с пометкой `filtered_out`

**Level 2 — Post-filters** (после AI-анализа):
- AI score < 30 — отклоняется
- Match percentage < 20% — отклоняется

### 2.5 AI-анализ вакансий v2 (JobAnalyzer)
- **С учётом профиля фрилансера:**
  - Навыки, опыт, предпочтительные категории
  - Сильные стороны, ставка
  - Подставляются в промпт для персонализации
- **Расширенный анализ:**
  - `suitable` — подходит ли
  - `score` — оценка 0-100
  - `priority` — low/medium/high
  - `reason` — объяснение
  - `extracted_budget` — извлечённый бюджет
  - `extracted_deadline` — извлечённый срок
  - `complexity` — low/medium/high
  - `skills_required` — требуемые навыки
  - `suggested_price` — предлагаемая цена
  - `risks` — риски
  - `match_percentage` — процент совпадения с профилем
- **Обработка ошибок:** RateLimitError, APIError, JSONDecodeError
- **Fallback:** Ollama (self-hosted LLM) если OpenAI недоступен

### 2.6 Генерация откликов v2 (ResponseGenerator)
- **С учётом профиля фрилансера:**
  - Навыки, опыт, сильные стороны
  - Ставка, портфолио
  - Подставляются в промпт
- **С учётом истории:**
  - Последние 10-15 откликов из БД используются для консистентности стиля
- **Fallback:** Шаблонный ответ с данными из профиля

### 2.7 Полуавтоматическая отправка откликов
- **Кнопки после генерации:**
  - 📋 Показать текст — для копирования
  - ✅ Отправить сейчас — через Telethon (для Telegram-каналов)
  - ✏️ Отредактировать — показать текст для ручной правки
  - 🔄 Сгенерировать заново — перегенерация
  - ⏳ Отложить — сохранить на потом
  - ❌ Отменить
- **Для Kwork:** показывает текст для ручной вставки на бирже
- **Авто-режим:** возможность автоматической отправки high-priority вакансий (настраивается)

### 2.8 Кулдаун рассылки
- Перед отправкой проверяется время с последней отправки в чат
- Хранится в БД (`chat_cooldowns`)
- По умолчанию 3600 секунд (1 час)
- Настраивается через бот

### 2.9 Telegram-бот (интерфейс)

#### Команды:
| Команда | Описание |
|---------|----------|
| `/start` | Запуск бота |
| `/help` | Справка |
| `/check` | Ручная проверка источников |
| `/health` | Статус системы |
| `/stats` | Статистика вакансий |

#### Главное меню:
| Кнопка | Действие |
|--------|----------|
| 📋 Вакансии | Просмотр новых вакансий |
| ⚙️ Настройки | Промпты, бюджет, кулдаун, фильтры |
| 📡 Источники | Управление источниками |
| 👤 Профиль | Профиль фрилансера |
| 📊 Статистика | Статистика по вакансиям |
| ❓ Помощь | Справка |

#### Управление источниками:
- Добавление (ConversationHandler): тип → название → URL
- Список, включение/выключение, удаление

#### Управление вакансиями:
- Красивое форматирование с эмодзи (приоритет, score, match)
- Детали: бюджет, срок, категория, навыки, рейтинг клиента, предложения
- Кнопки: ✅ Подходит, ❌ Не подходит, 💬 Отклик, 🚫 ЧС

#### Управление откликами:
- 📋 Показать текст (с markdown code block)
- ✅ Отправить (Telethon) / показать для Kwork
- ✏️ Отредактировать
- 🔄 Перегенерировать
- ⏳ Отложить
- ❌ Отменить

#### Настройки:
| Раздел | Параметры |
|--------|-----------|
| Промпты | Анализ, отклики |
| Бюджет | Мин/макс |
| Кулдаун | В минутах |
| Фильтры | Белый/чёрный список, рейтинг, предложения |
| Авто-режим | Вкл/выкл, задержка |

#### Профиль фрилансера:
| Поле | Описание |
|------|----------|
| Навыки | Через запятую |
| Опыт | Лет |
| Категории | Предпочтительные |
| Ставка | Руб/час |
| Сильные стороны | Для откликов |
| О себе | Bio |
| Портфолио | URL |

#### Безопасность:
- Все команды проверяют `OWNER_CHAT_ID`
- При отсутствии доступа: "У вас нет доступа"

---

## 3. Архитектура

### 3.1 Стиль
**Modular monolith** — один процесс, модули разделены по ответственности.

### 3.2 Слои
```
Telegram-интерфейс (handlers)
    ↓
Бизнес-логика (services: monitor, filters, analyzer, generator, sender)
    ↓
Интеграции (parsers + AI + Telethon + Ollama fallback)
    ↓
Персистентность (db: SQLite + migrations)
```

### 3.3 Поток данных
```
APScheduler (каждые 15 мин)
  → MonitorService.check_all_sources()
    → KworkParser.fetch_vacancies() [Playwright + stealth]
      → fetch_project_list() → fetch_project_detail() [полные детали]
    → TelegramSourceParser.fetch_messages_from_channel()
    → VacancyFilter.apply_pre_filters() [Level 1]
      → db.is_vacancy_seen() — дедупликация
      → db.save_vacancy() — сохранение (или filtered_out)
    → Для неотфильтрованных:
      → JobAnalyzer.analyze_job() [OpenAI / Ollama]
        → VacancyFilter.apply_post_filters() [Level 2]
          → db.update_vacancy_ai_analysis()
          → notify_new_vacancy() → bot.send_message() [quick actions]

Пользователь (через Telegram):
  → 📋 Вакансии → jobs_handler.show_vacancy()
  → 💬 Сгенерировать отклик → ResponseGenerator.generate_response()
    → с профилем + историей
  → ✅ Отправить → SenderService.send_message() [Telethon + кулдаун]
```

---

## 4. Структура файлов

```
freelance-radar/
├── bot/                          # Telegram-интерфейс
│   ├── handlers/
│   │   ├── sources_handler.py    # Управление источниками
│   │   ├── jobs_handler.py       # Просмотр вакансий + отклики v2
│   │   ├── settings_handler.py   # Настройки + фильтры + авто-режим
│   │   └── profile_handler.py    # Профиль фрилансера (NEW)
│   └── keyboards.py              # Все клавиатуры (расширенные)
│
├── services/                     # Бизнес-логика
│   ├── job_analyzer.py           # AI-анализ v2 (score, priority, profile)
│   ├── response_generator.py     # AI-отклики v2 (profile + history)
│   ├── monitor.py                # Мониторинг + интеграция фильтров
│   ├── sender.py                 # Отправка с кулдауном
│   ├── filters.py                # Двухуровневая фильтрация (NEW)
│   └── llm_fallback.py           # Ollama fallback (NEW)
│
├── parsers/                      # Парсеры
│   ├── base.py                   # Базовый класс
│   ├── kwork.py                  # Kwork v2 (stealth + full details)
│   ├── kwork_old.py              # Старый парсер (устарел)
│   └── telegram_source.py        # Telegram v2 (улучшенный)
│
├── db/                           # Персистентность
│   ├── models.py                 # Расширенные модели + FreelancerProfile
│   ├── queries.py                # Все запросы (расширенные)
│   └── init_db.py                # Схема + миграции
│
├── docker/
│   ├── Dockerfile                # Контейнеризация (NEW)
│   └── docker-compose.yml        # Compose (NEW)
│
├── config.py                     # Конфигурация
├── main.py                       # Точка входа (расширенная)
├── requirements.txt              # Зависимости (+tenacity, playwright)
├── .env                          # Секреты
├── .env.example                  # Шаблон
├── .gitignore
├── README.md
├── AGENTS.CLAUDE.md              # Инструкции для AI
├── PROJECT_FULL.md               # Этот файл
├── freelance_radar.db            # SQLite БД
├── freelance_radar_session.session  # Telethon сессия
│
├── docs/                         # Документация (пусто)
├── scripts/migrations/           # Миграции (пусто)
├── tests/unit/                   # Unit-тесты (пусто)
├── tests/integration/            # Integration-тесты (пусто)
│
└── test_*.py                     # Тестовые скрипты (в корне)
```

---

## 5. Модели данных (db/models.py)

### 5.1 JobVacancy (расширенная)
```python
@dataclass
class JobVacancy:
    kwork_id: str
    url: str
    title: str
    description: str
    budget: Optional[str] = None
    budget_min: Optional[int] = None          # NEW
    budget_max: Optional[int] = None          # NEW
    deadline: Optional[str] = None
    deadline_days: Optional[int] = None       # NEW
    category: Optional[str] = None
    subcategory: Optional[str] = None         # NEW
    skills: Optional[str] = None              # NEW (JSON)
    proposals_count: Optional[int] = None     # NEW
    customer_rating: Optional[float] = None   # NEW
    customer_orders: Optional[int] = None     # NEW
    source: str = "kwork"
    fetched_at: datetime = field(default_factory=datetime.now)
    analyzed: bool = False
    responded: bool = False
    # AI analysis fields (NEW)
    ai_score: Optional[int] = None            # 0-100
    ai_priority: Optional[str] = None         # low/medium/high
    ai_risks: Optional[str] = None
    match_percentage: Optional[int] = None
    # Filter fields (NEW)
    filtered_out: bool = False
    filter_reason: Optional[str] = None
```

### 5.2 Source
```python
@dataclass
class Source:
    id: Optional[int]
    name: str
    source_type: str       # "kwork" или "telegram"
    url: Optional[str]
    enabled: bool = True
    created_at: Optional[datetime] = None
```

### 5.3 UserSettings
```python
@dataclass
class UserSettings:
    id: Optional[int]
    user_id: int
    analysis_prompt: Optional[str]
    response_prompt: Optional[str]
    min_budget: Optional[int]
    max_budget: Optional[int]
    cooldown_seconds: int = 3600
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

### 5.4 FreelancerProfile (NEW)
```python
@dataclass
class FreelancerProfile:
    id: Optional[int]
    user_id: int
    skills: Optional[str] = None              # JSON list
    experience_years: Optional[int] = None
    preferred_categories: Optional[str] = None # JSON list
    hourly_rate: Optional[int] = None
    portfolio_url: Optional[str] = None
    bio: Optional[str] = None
    strong_sides: Optional[str] = None
    # Filter preferences
    min_customer_rating: Optional[float] = None
    max_proposals_count: Optional[int] = None
    whitelist_words: Optional[str] = None     # JSON list
    blacklist_words: Optional[str] = None     # JSON list
    auto_mode_enabled: bool = False
    auto_mode_delay_minutes: int = 5
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

### 5.5 Response
```python
@dataclass
class Response:
    id: Optional[int]
    vacancy_id: int
    kwork_id: str
    response_text: str
    approved: bool = False
    sent: bool = False
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
```

### 5.6 ChatCooldown
```python
@dataclass
class ChatCooldown:
    id: Optional[int]
    chat_id: str
    last_sent_at: datetime
    cooldown_seconds: int
```

---

## 6. Схема базы данных

### Таблица `vacancies` (расширенная)
```sql
CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kwork_id TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    budget TEXT,
    budget_min INTEGER,               -- NEW
    budget_max INTEGER,               -- NEW
    deadline TEXT,
    deadline_days INTEGER,            -- NEW
    category TEXT,
    subcategory TEXT,                 -- NEW
    skills TEXT,                      -- NEW
    proposals_count INTEGER,          -- NEW
    customer_rating REAL,             -- NEW
    customer_orders INTEGER,          -- NEW
    source TEXT NOT NULL DEFAULT 'kwork',
    fetched_at TEXT NOT NULL,
    analyzed INTEGER NOT NULL DEFAULT 0,
    responded INTEGER NOT NULL DEFAULT 0,
    ai_score INTEGER,                 -- NEW
    ai_priority TEXT,                 -- NEW
    ai_risks TEXT,                    -- NEW
    match_percentage INTEGER,         -- NEW
    filtered_out INTEGER NOT NULL DEFAULT 0,  -- NEW
    filter_reason TEXT                -- NEW
);
```

### Таблица `sources`
```sql
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
```

### Таблица `user_settings`
```sql
CREATE TABLE IF NOT EXISTS user_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    analysis_prompt TEXT,
    response_prompt TEXT,
    min_budget INTEGER,
    max_budget INTEGER,
    cooldown_seconds INTEGER NOT NULL DEFAULT 3600,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### Таблица `freelancer_profile` (NEW)
```sql
CREATE TABLE IF NOT EXISTS freelancer_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    skills TEXT,
    experience_years INTEGER,
    preferred_categories TEXT,
    hourly_rate INTEGER,
    portfolio_url TEXT,
    bio TEXT,
    strong_sides TEXT,
    min_customer_rating REAL,
    max_proposals_count INTEGER,
    whitelist_words TEXT,
    blacklist_words TEXT,
    auto_mode_enabled INTEGER NOT NULL DEFAULT 0,
    auto_mode_delay_minutes INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### Таблица `responses`
```sql
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL,
    kwork_id TEXT NOT NULL,
    response_text TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    FOREIGN KEY (vacancy_id) REFERENCES vacancies(id)
);
```

### Таблица `chat_cooldowns`
```sql
CREATE TABLE IF NOT EXISTS chat_cooldowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL UNIQUE,
    last_sent_at TEXT NOT NULL,
    cooldown_seconds INTEGER NOT NULL
);
```

### Индексы
```sql
CREATE INDEX IF NOT EXISTS idx_vacancies_kwork_id ON vacancies(kwork_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_source ON vacancies(source);
CREATE INDEX IF NOT EXISTS idx_vacancies_analyzed ON vacancies(analyzed);
CREATE INDEX IF NOT EXISTS idx_vacancies_filtered_out ON vacancies(filtered_out);  -- NEW
CREATE INDEX IF NOT EXISTS idx_vacancies_ai_priority ON vacancies(ai_priority);    -- NEW
CREATE INDEX IF NOT EXISTS idx_responses_vacancy_id ON responses(vacancy_id);
CREATE INDEX IF NOT EXISTS idx_responses_approved ON responses(approved);
CREATE INDEX IF NOT EXISTS idx_chat_cooldowns_chat_id ON chat_cooldowns(chat_id);
CREATE INDEX IF NOT EXISTS idx_freelancer_profile_user_id ON freelancer_profile(user_id);  -- NEW
```

### Миграции
`db/init_db.py` теперь включает `run_migrations()`, который:
1. Проверяет существующие колонки в `vacancies`
2. Добавляет недостающие через `ALTER TABLE ADD COLUMN`
3. Создаёт таблицу `freelancer_profile`, если не существует
4. Создаёт новые индексы

---

## 7. Все SQL-запросы (db/queries.py)

### Вакансии
| Функция | Назначение |
|---------|-----------|
| `is_vacancy_seen(db, kwork_id)` | Дедупликация |
| `save_vacancy(db, vacancy)` | Сохранить (все новые поля) |
| `update_vacancy_ai_analysis(db, ...)` | Обновить AI-поля |
| `mark_vacancy_filtered(db, kwork_id, reason)` | Пометить отфильтрованной |
| `get_unseen_vacancies(db, limit)` | Новые + не отфильтрованные |
| `get_high_priority_vacancies(db, limit)` | High priority + не откликнутые |
| `mark_vacancy_analyzed(db, kwork_id)` | Проанализирована |
| `mark_vacancy_responded(db, kwork_id)` | Откликнулись |
| `get_vacancy_by_kwork_id(db, kwork_id)` | Получить по ID |
| `get_vacancy_stats(db)` | Статистика (NEW) |

### Источники
| Функция | Назначение |
|---------|-----------|
| `add_source(db, source)` | Добавить |
| `get_enabled_sources(db)` | Включённые |
| `get_all_sources(db)` | Все |
| `toggle_source(db, source_id)` | Вкл/выкл |
| `delete_source(db, source_id)` | Удалить |

### Настройки
| Функция | Назначение |
|---------|-----------|
| `get_user_settings(db, user_id)` | Получить |
| `save_user_settings(db, settings)` | Сохранить/обновить |

### Профиль фрилансера (NEW)
| Функция | Назначение |
|---------|-----------|
| `get_freelancer_profile(db, user_id)` | Получить профиль |
| `save_freelancer_profile(db, profile)` | Сохранить/обновить |

### Отклики
| Функция | Назначение |
|---------|-----------|
| `save_response(db, response)` | Сохранить |
| `approve_response(db, response_id)` | Одобрить |
| `get_response_by_id(db, response_id)` | Получить |
| `get_recent_responses(db, limit)` | Недавние для контекста (NEW) |
| `mark_response_sent(db, response_id)` | Отправлен |

### Кулдаун
| Функция | Назначение |
|---------|-----------|
| `get_chat_cooldown(db, chat_id)` | Получить |
| `update_chat_cooldown(db, chat_id, cooldown_seconds)` | Обновить |
| `can_send_to_chat(db, chat_id, cooldown_seconds)` | Проверить |

---

## 8. Конфигурация (config.py)

### Переменные окружения (.env)
| Переменная | Описание | По умолчанию |
|------------|----------|-------------|
| `BOT_TOKEN` | Telegram Bot токен | (обязательно) |
| `OWNER_CHAT_ID` | Telegram user ID владельца | (обязательно) |
| `OPENAI_API_KEY` | API ключ OpenAI | (обязательно) |
| `TELEGRAM_API_ID` | API ID Telegram | (обязательно) |
| `TELEGRAM_API_HASH` | API Hash Telegram | (обязательно) |
| `DB_PATH` | Путь к файлу БД | `freelance_radar.db` |
| `KWORK_PROJECTS_URL` | URL листинга Kwork | `https://kwork.ru/projects` |
| `KWORK_REQUEST_DELAY_MIN` | Мин. задержка (сек) | `2.0` |
| `KWORK_REQUEST_DELAY_MAX` | Макс. задержка (сек) | `5.0` |
| `KWORK_MAX_PAGES` | Макс. страниц за цикл | `1` |
| `MONITOR_INTERVAL_MINUTES` | Интервал мониторинга | `15` |
| `DEFAULT_COOLDOWN_SEC` | Кулдаун по умолчанию | `3600` |

### Константы
| Константа | Значение | Описание |
|-----------|----------|----------|
| `OPENAI_MODEL` | `gpt-4o-mini` | Модель OpenAI |
| `USER_AGENT` | Chrome 120 | Для HTTP-запросов |

---

## 9. Зависимости (requirements.txt)

| Пакет | Версия | Назначение |
|-------|--------|-----------|
| `python-telegram-bot` | 20.8 | Telegram Bot API |
| `openai` | 1.12.0 | OpenAI API |
| `httpx` | ~0.26.0 | HTTP-запросы |
| `beautifulsoup4` | 4.12.3 | Парсинг HTML |
| `aiosqlite` | 0.20.0 | Async SQLite |
| `python-dotenv` | 1.0.1 | Загрузка .env |
| `APScheduler` | 3.10.4 | Планировщик |
| `Telethon` | 1.36.0 | Telegram User API |
| `tenacity` | 8.2.3 | Retry механизмы |
| `playwright` | 1.41.0 | Браузерная автоматизация |

---

## 10. Клавиатуры (bot/keyboards.py)

| Функция | Тип | Назначение |
|---------|-----|-----------|
| `main_menu_keyboard()` | Reply | Главное меню (6 кнопок) |
| `sources_keyboard()` | Inline | Источники |
| `source_type_keyboard()` | Inline | Тип источника |
| `source_actions_keyboard()` | Inline | Действия с источником |
| `vacancy_keyboard()` | Inline | Действия с вакансией |
| `quick_vacancy_actions_keyboard()` | Inline | Быстрые действия в уведомлении |
| `response_keyboard()` | Inline | Действия с откликом (6 кнопок) |
| `settings_keyboard()` | Inline | Настройки |
| `filters_settings_keyboard()` | Inline | Фильтры |
| `profile_keyboard()` | Inline | Профиль (8 полей) |
| `auto_mode_keyboard()` | Inline | Авто-режим |
| `stats_keyboard()` | Inline | Статистика |
| `confirm_keyboard()` | Inline | Подтверждение |
| `cancel_keyboard()` | Inline | Отмена |

---

## 11. Детальное описание модулей

### 11.1 main.py
- **Новые команды:** `/health`, `/stats`
- **scheduled_check()** теперь:
  1. Получает вакансии из парсеров
  2. Применяет pre-filters
  3. AI-анализ с профилем
  4. Применяет post-filters
  5. Отправляет уведомления с quick actions
- **notify_new_vacancy()** — форматированное уведомление с эмодзи
- **Регистрация всех handlers:**
  - Conversation handlers: sources, settings, profile
  - Callback handlers: быстрые действия, фильтры, авто-режим

### 11.2 bot/handlers/profile_handler.py (NEW)
- ConversationHandler с 7 состояниями:
  - ENTERING_SKILLS, ENTERING_EXPERIENCE, ENTERING_CATEGORIES
  - ENTERING_HOURLY_RATE, ENTERING_STRONG_SIDES
  - ENTERING_BIO, ENTERING_PORTFOLIO
- `profile_menu()` — показ текущего профиля
- `_update_profile_field()` — хелпер для сохранения полей

### 11.3 bot/handlers/settings_handler.py (расширенный)
- **Новые настройки:**
  - Белый список слов (ENTERING_WHITELIST)
  - Чёрный список слов (ENTERING_BLACKLIST)
  - Мин. рейтинг заказчика (ENTERING_MIN_RATING)
  - Макс. предложений (ENTERING_MAX_PROPOSALS)
  - Задержка авто-режима (ENTERING_AUTO_DELAY)
- `filters_menu()` — показ текущих фильтров
- `auto_mode_menu()` — управление авто-режимом

### 11.4 bot/handlers/jobs_handler.py (расширенный)
- `_format_vacancy_text()` — красивое форматирование с эмодзи
- Показ: priority emoji, score, match, risks
- **Новые actions:**
  - `vacancy_blacklist()` — добавить в чёрный список
  - `vacancy_detail()` — подробный просмотр
  - `response_send()` — отправка через Telethon
  - `response_edit()` — показать для редактирования
  - `response_defer()` — отложить

### 11.5 services/job_analyzer.py (v2)
- `analyze_job(vacancy, custom_prompt, profile)` — с профилем
- Расширенный JSON-ответ:
  - score (0-100), priority, match_percentage
  - suggested_price, risks
- `_format_profile_for_prompt()` — форматирование профиля для AI

### 11.6 services/response_generator.py (v2)
- `generate_response(vacancy, custom_prompt, profile, recent_responses)`
- Использует профиль + последние 10-15 откликов
- Расширенный fallback с данными профиля

### 11.7 services/filters.py (NEW)
- `VacancyFilter` класс:
  - `apply_pre_filters(vacancy)` — Level 1
  - `apply_post_filters(vacancy)` — Level 2
  - Поддержка: budget, blacklist, whitelist, rating, proposals
- `quick_budget_filter()` — быстрая фильтрация по тексту

### 11.8 services/monitor.py (расширенный)
- Интеграция `VacancyFilter`
- Pre-filters применяются перед сохранением
- Отфильтрованные вакансии сохраняются с `filtered_out=True`

### 11.9 services/llm_fallback.py (NEW)
- `LLMFallback` — клиент Ollama
- `is_available()` — проверка доступности
- `analyze_job()` — анализ через локальную модель
- `generate_response()` — генерация через локальную модель
- `get_llm_client()` — выбор между OpenAI и Ollama

### 11.10 parsers/kwork.py (v2)
- **Stealth:**
  - USER_AGENTS (4 штуки)
  - VIEWPORTS (4 штуки)
  - `_get_stealth_headers()` — расширенные заголовки
- **Полный парсинг:**
  - `fetch_project_list()` — список URL через Playwright
  - `fetch_project_detail()` — полные детали по каждому
  - Extractors: title, description, budget_text, budget_range,
    deadline_text, deadline_days, category, subcategory, skills,
    proposals_count, customer_rating, customer_orders

### 11.11 parsers/telegram_source.py (v2)
- Улучшенные extractors:
  - `_extract_budget_range()` — min/max
  - `_extract_deadline_days()` — срок в днях
  - `_extract_category_from_text()` — категория из хэштегов
  - `_extract_skills_from_text()` — навыки из хэштегов

---

## 12. Docker (NEW)

### Dockerfile
- Базовый образ: `python:3.11-slim`
- Установка системных зависимостей для Playwright
- Установка Chromium через `playwright install chromium`
- Команда запуска: `python db/init_db.py && python main.py`

### docker-compose.yml
- Сервис `bot`
- Volume для БД и session-файла
- Environment из `.env`
- Logging: json-file, max-size 10m

---

## 13. Как запустить

### 13.1 Подготовка
```bash
# 1. Создать виртуальное окружение
python -m venv venv

# 2. Активировать
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Установить Playwright
playwright install chromium

# 5. Скопировать .env.example в .env и заполнить
cp .env.example .env

# 6. Инициализировать БД (с миграциями)
python db/init_db.py
```

### 13.2 Запуск
```bash
python main.py
```

### 13.3 Docker
```bash
docker-compose up -d
```

---

## 14. Команды

| Команда | Описание |
|---------|----------|
| `pip install -r requirements.txt` | Установка зависимостей |
| `python main.py` | Запуск бота |
| `python db/init_db.py` | Инициализация/миграция БД |
| `playwright install chromium` | Установка браузера |
| `docker-compose up -d` | Запуск в Docker |
| `flake8 . --max-line-length=120` | Lint |
| `black . --line-length 120` | Format |
| `pytest tests/ -v` | Тесты |

---

## 15. Безопасность

### Жёсткие правила:
- Не коммитить `.env`, `*.session`, API-ключи
- Не хардкодить токены в коде
- Бот только для `OWNER_CHAT_ID`
- Нельзя отправлять без одобрения (в MVP)
- Нельзя рассылать без кулдауна
- Все HTTP-запросы через Playwright/httpx (async)

### Чувствительные данные:
- BOT_TOKEN, OPENAI_API_KEY
- TELEGRAM_API_ID, TELEGRAM_API_HASH
- *.session файлы

---

## 16. Что реализовано (v2.0)

| Функция | Статус |
|---------|--------|
| Telegram-бот | ✅ |
| Мониторинг Kwork v2 (stealth + детали) | ✅ |
| Мониторинг Telegram v2 | ✅ |
| AI-анализ v2 (score, priority, match) | ✅ |
| AI-отклики v2 (profile + history) | ✅ |
| Двухуровневая фильтрация | ✅ |
| Профиль фрилансера | ✅ |
| Кулдаун рассылки | ✅ |
| Источники (CRUD) | ✅ |
| Промпты (анализ + отклики) | ✅ |
| Бюджет (min/max) | ✅ |
| Фильтры (whitelist, blacklist, rating, proposals) | ✅ |
| Авто-режим | ✅ |
| Полуавтоматическая отправка | ✅ |
| Красивое отображение вакансий | ✅ |
| Quick actions в уведомлениях | ✅ |
| Статистика (/stats) | ✅ |
| Health check (/health) | ✅ |
| Docker + docker-compose | ✅ |
| Self-hosted LLM fallback (Ollama) | ✅ |
| Миграции БД | ✅ |
| Retry (tenacity) | ✅ (зависимость добавлена) |
| E2E тесты | ❌ |
| Unit тесты | ✅ (32 теста, все проходят) |
| Integration тесты | ❌ |

---

## 18. Что нового в v2.1 (финальный апгрейд)

### 🔥 Критично важное

| Функция | Статус |
|---------|--------|
| KworkParser v2 с retry (tenacity) | ✅ 3 попытки, экспоненциальная задержка |
| Stealth-режим улучшен | ✅ 5 User-Agent, geolocation Moscow, cookies |
| Rate limiting Kwork | ✅ 200 запросов/сутки, адаптивные задержки (ночь ×2) |
| structlog логирование | ✅ JSON + console + файл logs/freelance_radar.log |

### Высокий приоритет

| Функция | Статус |
|---------|--------|
| Мониторинг и алерты | ✅ /health, уведомление при >40 мин без проверки, critical errors |
| Уведомления о новых вакансиях | ✅ Quick actions (Отклик, Пропустить, ЧС, Подробнее) |
| Отправка откликов | ✅ Telegram через Telethon, Kwork — копирование |

### Средний приоритет

| Функция | Статус |
|---------|--------|
| Unit тесты | ✅ 32 теста (parsers, filters, analyzer) |
| Статистика /stats | ✅ Конверсия, % high priority, % отфильтрованных |
| Blacklist service | ✅ Вакансии и заказчики |
| Ollama fallback | ✅ Полноценный fallback если OpenAI недоступен |

---

*Документ обновлён после финального апгрейда до v2.1 — 32 теста проходят, структурированное логирование, rate limiting, мониторинг и алерты.*
