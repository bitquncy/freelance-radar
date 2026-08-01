# FreelanceRadar

Telegram-бот для мониторинга фриланс-бирж с AI-анализом, автоматической генерацией откликов и двухуровневой фильтрацией вакансий.

## Содержание

- [Обзор](#обзор)
- [Возможности](#возможности)
- [Архитектура](#архитектура)
- [Требования](#требования)
- [Установка](#установка)
- [Docker-деплой](#docker-деплой)
- [Конфигурация](#конфигурация)
- [Использование](#использование)
- [Структура проекта](#структура-проекта)
- [Модели данных](#модели-данных)
- [Разработка](#разработка)
- [Тестирование](#тестирование)
- [Лицензия](#лицензия)

---

## Обзор

FreelanceRadar — это персональный Telegram-бот, который автоматически мониторит фриланс-биржи (Kwork, Telegram-каналы), анализирует вакансии с помощью AI и генерирует персонализированные отклики.

**Стек технологий:**
- Python 3.11+
- Telegram Bot API (python-telegram-bot 20.x)
- OpenAI API (gpt-4o-mini) **или OpenRouter** (дешевле, больше моделей)
- Ollama fallback
- Playwright (парсинг Kwork)
- Telethon (парсинг Telegram)
- PostgreSQL в production, SQLite для локальной разработки и тестов
- APScheduler (планировщик задач)
- structlog (структурированное логирование)
- tenacity (retry логика)
- matplotlib (графики)
- pytest (тестирование)

---

## Возможности

### Мониторинг
- Автоматическая проверка Kwork каждые 15 минут (настраивается)
- Поддержка Telegram-каналов как источников вакансий
- Стелс-режим парсинга (user-agent, viewport, route blocking)
- Rate limiting для Kwork (200 запросов/день)
- Rate limiting для OpenAI API (20 RPM, min_delay 3s)

### AI-анализ
- Двухуровневая фильтрация: pre-filters (до AI) и post-filters (после AI)
- Scoring: оценка вакансий от 0 до 100
- Приоритизация: low / medium / high
- Процент совпадения с профилем фрилансера
- Оценка рисков и сложности
- Автоматический ответ для high-priority вакансий (auto-mode)

### Генерация откликов
- Персонализированные отклики на основе профиля фрилансера
- Учёт навыков, опыта, ставки и сильных сторон
- Контекст предыдущих откликов для единообразия стиля
- Ручное редактирование перед отправкой

### Безопасная рассылка
- `/broadcast` — админский раздел рассылок через Bot API
- Получатели добавляются вручную; бот проверяет своё право публикации в каждом чате
- Исходное сообщение копируется без метки «переслано» (текст, фото, видео, документ)
- Отложенный запуск, прогресс, пауза, возобновление и остановка
- Устойчивая очередь с отдельным статусом каждого получателя и восстановлением без дублей
- Консервативный лимит скорости и часовой кулдаун одного чата по умолчанию
- Telethon-сессия мониторинга остаётся read-only; автопоиска и автовступления в группы нет

### Управление
- `/start` — запуск бота
- `/help` — справка
- `/check` — ручная проверка источников
- `/health` — статус системы
- `/stats` — статистика вакансий
- `/search <query>` — поиск по базе (FTS5)
- `/chart` — графики статистики (4 типа)
- `/blacklist` — управление чёрным списком
- Пагинация списка вакансий
- Отложенные вакансии
- Кулдаун для рассылки сообщений

### Производительность
- AI Cache — LRU кэш с TTL 24ч для OpenAI ответов
- Batch анализ — параллельный анализ вакансий (max 5 concurrent)
- Batch DB операции — bulk insert/update через executemany
- PostgreSQL-first в production, SQLite-only для локальной разработки

### Мониторинг и трассировка
- Метрики Prometheus — Counter, Gauge, Histogram, Timer
- Трассировка — span-based tracing для каждого этапа
- Alerting — алерты при ошибках (парсинг, Kwork, OpenAI, мониторинг)
- EventBus — событийная архитектура (publish/subscribe)
- Логирование с ротацией — RotatingFileHandler (10MB, 5 файлов)

### Архитектура
- DI-контейнер — ServiceRegistry для управления зависимостями
- AuthMiddleware — middleware для авторизации в python-telegram-bot
- Event-driven — публикация событий на каждом этапе pipeline
- Метрики из событий — автоматический сбор метрик через middleware
- Production runtime: PostgreSQL, Alembic migrations, one bot replica with local FSM storage

### Безопасность
- Auth middleware: `@owner_only` на всех владельческих обработчиках
- Blacklist с TTL (expires_at)
- Уникальные constraints для ключевых сущностей и идемпотентных операций
- Graceful shutdown при SIGTERM/SIGINT
- Конкретные типы ошибок вместо `except Exception`

---

## Архитектура

### Общая схема

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Bot API                         │
│                    (python-telegram-bot)                    │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    Bot Layer (bot/)                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ handlers │ │ keyboards│ │ auth.py  │ │ middleware│       │
│  │ jobs     │ │          │ │ @owner_  │ │ AuthMid  │       │
│  │ sources  │ │          │ │  only    │ │          │       │
│  └────┬─────┘ └──────────┘ └──────────┘ └──────────┘       │
└───────┼─────────────────────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────────────────────┐
│                  Services Layer (services/)                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │ job_analyzer │ │ response_gen │ │   monitor    │         │
│  │ (OpenAI)     │ │ (OpenAI)     │ │   (APScheduler)        │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘         │
│  ┌──────┴───────┐ ┌──────┴───────┐ ┌──────┴───────┐         │
│  │   filters    │ │  blacklist   │ │  rate_limiter│         │
│  │ (pre+post)   │ │  (TTL)       │ │  (Kwork+AI)  │         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │  ai_cache    │ │  event_bus   │ │ dependencies │         │
│  │ (LRU+TTL)    │ │ (pub/sub)    │ │ (DI container)         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │  metrics     │ │  tracing     │ │  alerting    │         │
│  │ (Prometheus) │ │ (spans)      │ │ (rules)      │         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
└───────┼─────────────────────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────────────────────┐
│                  Parser Layer (parsers/)                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │  base.py     │ │   kwork.py   │ │ telegram_src │         │
│  │  (ABC)       │ │  (Playwright)│ │  (Telethon)  │         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
└───────┼─────────────────────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────────────────────┐
│                  Database Layer (db/)                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │   models.py  │ │  queries.py  │ │  init_db.py  │         │
│  │ (dataclass)  │ │  (CRUD+FTS)  │ │  (migrations)│         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
│  ┌──────────────┐ ┌──────────────┐                           │
│  │  database.py │ │   utils.py   │                           │
│  │ (connection) │ │  (parsers)   │                           │
│  └──────────────┘ └──────────────┘                           │
│                  SQLite (aiosqlite) + FTS5                   │
└─────────────────────────────────────────────────────────────┘
```

### Поток данных

1. **APScheduler** вызывает `scheduled_check()` каждые N минут
2. **MonitorService** проверяет Kwork (Playwright + stealth) и Telegram
3. **VacancyFilter** применяет pre-filters (бюджет, blacklist, whitelist)
4. **JobAnalyzer** использует OpenAI GPT-4o-mini для анализа
5. **VacancyFilter** применяет post-filters (AI score < 30, match < 20%)
6. **Уведомления** отправляются владельцу через Telegram с кнопками
7. **ResponseGenerator** создаёт персонализированные отклики

### Ключевые паттерны

- **Modular monolith** — все модули в одном процессе, но разделены по слоям
- **ABC base parser** — абстрактный класс для расширения новыми источниками
- **Двухуровневая фильтрация** — pre-filters (дешёвые) и post-filters (AI-анализ)
- **Rate limiting** — токен bucket для Kwork и OpenAI
- **Graceful shutdown** — обработка SIGTERM/SIGINT для корректной остановки Playwright

---

## Требования

- Python 3.11+
- Telegram Bot Token (получить у [@BotFather](https://t.me/BotFather))
- **OpenRouter API Key** (рекомендуется, дешевле) — получить на [openrouter.ai](https://openrouter.ai/keys)
  - **ИЛИ** OpenAI API Key — получить на [platform.openai.com](https://platform.openai.com)
- Telegram API ID и Hash (получить на [my.telegram.org](https://my.telegram.org)) — опционально
- PostgreSQL для production

---

## Установка

### Локальная установка

Локально можно использовать SQLite, но production требует PostgreSQL.

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd freelance-radar
```

2. Создайте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Установите Playwright браузеры:
```bash
playwright install chromium
playwright install-deps chromium
```

5. Скопируйте `.env.example` в `.env` и заполните:
```bash
cp .env.example .env
```

6. Отредактируйте `.env` (см. [Конфигурация](#конфигурация))

7. Инициализируйте базу данных:
```bash
python db/init_db.py
```

8. Запустите бота:
```bash
python main.py
```

При первом запуске Telethon попросит ввести номер телефона и код подтверждения для создания сессии.

---

## Docker-деплой

См. также `docs/PRODUCTION_OPERATIONS.md` для production-first деплоя, backup/restore и retention.

### Требования

- Docker
- Docker Compose

### Быстрый старт

1. Создайте `.env` файл:
```bash
cp .env.example .env
# Заполните .env своими значениями
```

2. Запустите контейнер:
```bash
docker compose up -d
```

3. Проверьте статус:
```bash
docker compose logs -f
```

4. Остановите:
```bash
docker compose down
```

### Конфигурация Docker

`docker-compose.yml`:
```yaml
version: '3.8'

services:
  bot:
    build: .
    container_name: freelance-radar
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - ./freelance_radar.db:/app/freelance_radar.db
      - ./freelance_radar_session.session:/app/freelance_radar_session.session
    environment:
      - DB_PATH=freelance_radar.db
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Важные заметки

- Директория `data/` хранит данные приложения
- Файл `freelance_radar.db` — база данных SQLite
- Файл `freelance_radar_session.session` — сессия Telethon (не пересоздавайте!)
- При первом запуске нужно будет ввести код подтверждения Telethon

---

## Конфигурация

### Переменные окружения (`.env`)

```env
# Telegram Bot Configuration
BOT_TOKEN=your_bot_token_here
OWNER_CHAT_ID=your_telegram_user_id_here

# AI Configuration (OpenRouter рекомендуется, дешевле)
# Вариант 1 - OpenRouter
OPENAI_API_KEY=your_openrouter_api_key_here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-4o-mini

# Вариант 2 - OpenAI напрямую
# OPENAI_API_KEY=your_openai_api_key_here
# OPENAI_MODEL=gpt-4o-mini

# Telegram User API (for Telethon)
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here

# Database Configuration
DB_PATH=freelance_radar.db

# Kwork Parser Configuration
KWORK_PROJECTS_URL=https://kwork.ru/projects
KWORK_REQUEST_DELAY_MIN=2.0
KWORK_REQUEST_DELAY_MAX=5.0
KWORK_MAX_PAGES=1
KWORK_MAX_DETAIL_PAGES=5

# Monitoring Configuration
MONITOR_INTERVAL_MINUTES=15

# Default Settings
DEFAULT_COOLDOWN_SEC=3600
```

### Описание параметров

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `BOT_TOKEN` | — | Токен Telegram бота (обязательно) |
| `OWNER_CHAT_ID` | — | ID владельца бота (обязательно) |
| `OPENAI_API_KEY` | — | API ключ OpenAI/OpenRouter (обязательно) |
| `OPENAI_BASE_URL` | `None` | Base URL для OpenRouter (опционально) |
| `OPENAI_MODEL` | `gpt-4o-mini` | Модель AI (для OpenRouter используйте формат `provider/model`) |
| `TELEGRAM_API_ID` | — | Telegram API ID (обязательно) |
| `TELEGRAM_API_HASH` | — | Telegram API Hash (обязательно) |
| `DB_PATH` | `freelance_radar.db` | Путь к базе данных |
| `KWORK_PROJECTS_URL` | `https://kwork.ru/projects` | URL проектов Kwork |
| `KWORK_REQUEST_DELAY_MIN` | `2.0` | Минимальная задержка между запросами (сек) |
| `KWORK_REQUEST_DELAY_MAX` | `5.0` | Максимальная задержка между запросами (сек) |
| `KWORK_MAX_PAGES` | `1` | Максимальное количество страниц для парсинга |
| `KWORK_MAX_DETAIL_PAGES` | `5` | Максимальное количество страниц с деталями |
| `MONITOR_INTERVAL_MINUTES` | `15` | Интервал проверки источников (мин) |
| `DEFAULT_COOLDOWN_SEC` | `3600` | Кулдаун рассылки (сек) |
| `BROADCAST_RATE_LIMIT` | `10` | Максимальная средняя скорость Bot API рассылки (сообщений/сек) |
| `BROADCAST_BATCH_SIZE` | `10` | Максимальный параллельный батч получателей |
| `BROADCAST_MAX_RETRIES` | `3` | Повторы при временных ошибках Telegram |
| `BROADCAST_PROGRESS_INTERVAL` | `5` | Интервал обновления прогресса (сек) |
| `BROADCAST_MIN_CHAT_INTERVAL_SEC` | `3600` | Минимальный интервал между рассылками в один чат |
| `BROADCAST_TIMEZONE` | `Asia/Yekaterinburg` | Часовой пояс планировщика рассылок |

---

## Использование

### Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Запустить бота |
| `/help` | Показать справку |
| `/check` | Проверить источники вручную |
| `/health` | Статус системы |
| `/stats` | Статистика вакансий |
| `/blacklist` | Управление чёрным списком |
| `/broadcast` | Рассылка по разрешённым чатам (только владелец) |

### Меню бота

- **📋 Вакансии** — Просмотр новых вакансий с пагинацией
- **⚙️ Настройки** — Настройка промптов, бюджета, кулдауна, фильтров, авто-режима
- **📡 Источники** — Управление источниками мониторинга (Kwork, Telegram)
- **👤 Профиль** — Профиль фрилансера (навыки, опыт, ставка)
- **📊 Статистика** — Статистика по вакансиям

### Добавление источников

1. Нажмите "📡 Источники"
2. Выберите "➕ Добавить источник"
3. Выберите тип (Kwork или Telegram)
4. Введите название и URL (для Telegram)

### Настройка промптов

1. Нажмите "⚙️ Настройки"
2. Выберите нужный промпт (для анализа или для откликов)
3. Введите свой текст

### Авто-режим

При включённом авто-режиме бот автоматически генерирует отклики для high-priority вакансий.

1. Нажмите "⚙️ Настройки"
2. Выберите "🔍 Фильтры"
3. Выберите "🤖 Авто-режим"
4. Нажмите "▶️ Включить"

---

## Структура проекта

```
freelance-radar/
├── bot/                          # Telegram-интерфейс
│   ├── auth.py                   # Auth middleware (@owner_only)
│   ├── keyboards.py              # Все клавиатуры (Reply + Inline)
│   ├── middleware.py              # AuthMiddleware для python-telegram-bot
│   └── handlers/
│       ├── jobs_handler.py       # Просмотр/управление вакансиями
│       ├── sources_handler.py    # CRUD источников (ConversationHandler)
│       ├── settings_handler.py   # Настройки (промпты, бюджет, фильтры, авто-режим)
│       └── profile_handler.py    # Профиль фрилансера (ConversationHandler)
│
├── services/                     # Бизнес-логика
│   ├── job_analyzer.py           # AI-анализ (OpenAI) + кэш + batch
│   ├── response_generator.py     # AI-генерация откликов (OpenAI)
│   ├── monitor.py                # Мониторинг источников (APScheduler)
│   ├── sender.py                 # Отправка сообщений (Telethon)
│   ├── filters.py                # Двухуровневая фильтрация (pre + post)
│   ├── blacklist.py              # Blacklist service (TTL)
│   ├── rate_limiter.py           # Rate limiting (Kwork)
│   ├── openai_rate_limiter.py    # Rate limiting (OpenAI)
│   ├── llm_fallback.py           # Ollama fallback
│   ├── ai_cache.py               # LRU кэш для OpenAI (TTL 24ч)
│   ├── event_bus.py              # Event-driven архитектура (pub/sub)
│   ├── dependencies.py           # DI-контейнер (ServiceRegistry)
│   ├── metrics.py                # Метрики Prometheus
│   ├── tracing.py                # Трассировка (spans)
│   ├── alerting.py               # Алертинг (правила + cooldown)
│   ├── charts.py                 # Генерация графиков (matplotlib)
│   └── logger_config.py          # structlog + RotatingFileHandler
│
├── parsers/                      # Парсеры источников
│   ├── base.py                   # Базовый класс (ABC)
│   ├── kwork.py                  # Kwork v3 (Playwright + stealth)
│   ├── telegram_source.py        # Telegram (Telethon)
│   └── utils.py                  # Общие утилиты парсеров
│
├── db/                           # Персистентность
│   ├── models.py                 # Dataclass модели + JSON property-методы
│   ├── queries.py                # SQL-запросы (CRUD + FTS + batch)
│   ├── database.py               # Connection manager (WAL, pooling)
│   └── init_db.py                # Инициализация + миграции + FTS5
│
├── tests/                        # Тесты (142 tests)
│   ├── unit/
│   │   ├── test_analyzer.py
│   │   ├── test_auth.py
│   │   ├── test_auto_mode.py
│   │   ├── test_blacklist.py
│   │   ├── test_filters.py
│   │   ├── test_parsers.py
│   │   ├── test_ai_cache.py
│   │   ├── test_batch_queries.py
│   │   ├── test_database.py
│   │   ├── test_search.py
│   │   ├── test_dependencies.py
│   │   ├── test_middleware.py
│   │   ├── test_metrics.py
│   │   ├── test_tracing.py
│   │   ├── test_alerting.py
│   │   └── test_error_handling.py
│   └── integration/
│       ├── test_handlers.py
│       ├── test_monitor.py
│       └── test_scheduler.py
│
├── .github/workflows/ci.yml     # CI/CD pipeline
├── scripts/
│   ├── healthcheck.py            # Docker healthcheck
│   └── entrypoint.sh             # Docker entrypoint
├── config.py                     # Конфигурация (Pydantic)
├── constants.py                  # Константы и enum
├── main.py                       # Точка входа + DI + event bus
├── requirements.txt              # Зависимости
├── Dockerfile                    # Контейнеризация
├── docker-compose.yml            # Docker Compose
├── .env.example                  # Шаблон переменных окружения
├── .gitignore                    # Игнорируемые файлы
├── README.md                     # Эта документация
└── CHANGELOG.md                  # Changelog
```

---

## Модели данных

### JobVacancy

```python
@dataclass
class JobVacancy:
    kwork_id: str
    url: str
    title: str
    description: str
    budget: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    deadline: Optional[str] = None
    deadline_days: Optional[int] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    skills: Optional[str] = None          # JSON list (skills_list property)
    proposals_count: Optional[int] = None
    customer_rating: Optional[float] = None
    customer_orders: Optional[int] = None
    source: str = "kwork"
    fetched_at: datetime = field(default_factory=datetime.now)
    analyzed: bool = False
    responded: bool = False
    ai_score: Optional[int] = None        # 0-100
    ai_priority: Optional[str] = None     # low/medium/high
    ai_risks: Optional[str] = None
    match_percentage: Optional[int] = None
    filtered_out: bool = False
    filter_reason: Optional[str] = None

    @property
    def skills_list(self) -> List[str]:
        """Get skills as a list."""
        return _parse_json_list(self.skills)

    @skills_list.setter
    def skills_list(self, value):
        """Set skills from a list or string."""
        self.skills = _to_json_list(value)
```

### FreelancerProfile

```python
@dataclass
class FreelancerProfile:
    id: Optional[int]
    user_id: int
    skills: Optional[str] = None          # JSON list (skills_list property)
    experience_years: Optional[int] = None
    preferred_categories: Optional[str] = None  # JSON list
    hourly_rate: Optional[int] = None
    portfolio_url: Optional[str] = None
    bio: Optional[str] = None
    strong_sides: Optional[str] = None
    min_budget: Optional[int] = None
    max_budget: Optional[int] = None
    min_customer_rating: Optional[float] = None
    max_proposals_count: Optional[int] = None
    whitelist_words: Optional[str] = None  # JSON list
    blacklist_words: Optional[str] = None  # JSON list
    auto_mode_enabled: bool = False
    auto_mode_delay_minutes: int = 5

    @property
    def skills_list(self) -> List[str]:
        return _parse_json_list(self.skills)

    @property
    def preferred_categories_list(self) -> List[str]:
        return _parse_json_list(self.preferred_categories)

    @property
    def whitelist_words_list(self) -> List[str]:
        return _parse_json_list(self.whitelist_words)

    @property
    def blacklist_words_list(self) -> List[str]:
        return _parse_json_list(self.blacklist_words)
```

### Blacklist

```python
@dataclass
class Blacklist:
    id: Optional[int]
    entity_type: str        # 'vacancy' or 'customer'
    entity_id: str          # kwork_id or customer identifier
    reason: Optional[str]
    added_at: datetime
    user_id: int
    expires_at: Optional[datetime] = None  # TTL для чёрного списка
```

### Схема БД

```sql
-- Вакансии
CREATE TABLE vacancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kwork_id TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    budget TEXT,
    budget_min INTEGER,
    budget_max INTEGER,
    deadline TEXT,
    deadline_days INTEGER,
    category TEXT,
    subcategory TEXT,
    skills TEXT,
    proposals_count INTEGER,
    customer_rating REAL,
    customer_orders INTEGER,
    source TEXT NOT NULL DEFAULT 'kwork',
    fetched_at TEXT NOT NULL,
    analyzed INTEGER NOT NULL DEFAULT 0,
    responded INTEGER NOT NULL DEFAULT 0,
    ai_score INTEGER,
    ai_priority TEXT,
    ai_risks TEXT,
    match_percentage INTEGER,
    filtered_out INTEGER NOT NULL DEFAULT 0,
    filter_reason TEXT
);

-- Источники
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Настройки пользователя
CREATE TABLE user_settings (
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

-- Профиль фрилансера
CREATE TABLE freelancer_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    skills TEXT,
    experience_years INTEGER,
    preferred_categories TEXT,
    hourly_rate INTEGER,
    portfolio_url TEXT,
    bio TEXT,
    strong_sides TEXT,
    min_budget INTEGER,
    max_budget INTEGER,
    min_customer_rating REAL,
    max_proposals_count INTEGER,
    whitelist_words TEXT,
    blacklist_words TEXT,
    auto_mode_enabled INTEGER NOT NULL DEFAULT 0,
    auto_mode_delay_minutes INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Отклики
CREATE TABLE responses (
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

-- Кулдауны
CREATE TABLE chat_cooldowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL UNIQUE,
    last_sent_at TEXT NOT NULL,
    cooldown_seconds INTEGER NOT NULL
);

-- Чёрный список
CREATE TABLE blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT,
    added_at TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    expires_at TEXT,
    UNIQUE(entity_type, entity_id, user_id)
);

-- Индексы
CREATE INDEX idx_vacancies_kwork_id ON vacancies(kwork_id);
CREATE INDEX idx_vacancies_source ON vacancies(source);
CREATE INDEX idx_vacancies_analyzed ON vacancies(analyzed);
CREATE INDEX idx_responses_vacancy_id ON responses(vacancy_id);
CREATE INDEX idx_responses_approved ON responses(approved);
CREATE INDEX idx_chat_cooldowns_chat_id ON chat_cooldowns(chat_id);
CREATE INDEX idx_blacklist_entity ON blacklist(entity_type, entity_id, user_id);
```

---

## Разработка

### Добавление нового парсера

1. Создайте файл в `parsers/`
2. Наследуйтесь от `BaseParser`
3. Реализуйте методы:
   - `fetch_vacancies(limit: int = 10) -> List[JobVacancy]`
   - `fetch_project_list() -> List[str]`
   - `fetch_project_detail(url: str) -> Optional[JobVacancy]`
4. Добавьте в `services/monitor.py`
5. Добавьте тест в `tests/unit/`

### Добавление нового обработчика

1. Создайте обработчик в `bot/handlers/`
2. Добавьте `@owner_only` декоратор
3. Зарегистрируйте в `main.py`

### Добавление нового сервиса

1. Создайте файл в `services/`
2. Используйте `get_logger(__name__)` для логирования
3. Добавьте тесты в `tests/unit/`

---

## Тестирование

### Запуск тестов

```bash
pytest tests/ -v
```

### Запуск конкретного теста

```bash
pytest tests/unit/test_filters.py -v
```

### Структура тестов (142 tests)

**Unit тесты:**
- `test_analyzer.py` — 8 тестов (AI анализ)
- `test_auth.py` — 4 теста (auth middleware)
- `test_auto_mode.py` — 3 теста (auto-mode логика)
- `test_blacklist.py` — 7 тестов (blacklist service)
- `test_filters.py` — 12 тестов (фильтрация)
- `test_parsers.py` — 20 тестов (парсеры)
- `test_ai_cache.py` — 7 тестов (LRU кэш)
- `test_batch_queries.py` — 4 теста (batch операции)
- `test_database.py` — 4 теста (connection manager)
- `test_search.py` — 5 тестов (FTS поиск)
- `test_dependencies.py` — 10 тестов (DI-контейнер)
- `test_middleware.py` — 10 тестов (AuthMiddleware)
- `test_metrics.py` — 9 тестов (метрики)
- `test_tracing.py` — 10 тестов (трассировка)
- `test_alerting.py` — 10 тестов (алертинг)
- `test_error_handling.py` — 4 теста (error handling)

**Integration тесты:**
- `test_handlers.py` — 3 теста (форматирование)
- `test_monitor.py` — 9 тестов (фильтрация)
- `test_scheduler.py` — 1 тест (scheduler state)

---

## Лицензия

MIT

---

## V2: развитие по AGENTS.md (pre-MVP SaaS)

В репозитории идёт эволюция бота в подписочный сервис по спецификации
[AGENTS.md](AGENTS.md): мульти-тенантный мониторинг бирж, скоринг вероятности
и выгодности заказа, AI-отклики с guardrails, CRM с напоминаниями и тарифы.

- Слой включается флагом `RADAR_V2_ENABLED=true` (по умолчанию выключен,
  поведение текущего бота не меняется).
- Код: `core/` (модели, скоринг, генерация, CRM), `monitoring/` (адаптеры,
  коллектор, воркер), `bot/handlers/v2/`, `prompts/`, `alembic/`.
- Карта соответствия спеке и принятые решения: [docs/V2_IMPLEMENTATION.md](docs/V2_IMPLEMENTATION.md).
