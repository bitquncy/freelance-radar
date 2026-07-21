# FreelanceRadar — Полное описание проекта (v2.1)

---

## 1. Общая информация

| Параметр | Значение |
|----------|----------|
| **Название** | FreelanceRadar |
| **Тип** | Telegram-бот |
| **Назначение** | Мониторинг фриланс-бирж, AI-анализ, генерация откликов |
| **Язык** | Python 3.11+ |
| **Версия** | v2.1 (финальный апгрейд) |
| **Архитектура** | Modular monolith |
| **БД** | SQLite (aiosqlite) |
| **AI** | OpenAI (gpt-4o-mini) + Ollama fallback |
| **Парсинг** | Playwright (Kwork) + Telethon (Telegram) |
| **Логирование** | structlog + stdlib logging |
| **Планировщик** | APScheduler |
| **Лицензия** | MIT |

---

## 2. Структура файлов

```
freelance-radar/
├── bot/                              # Telegram-интерфейс
│   ├── handlers/
│   │   ├── jobs_handler.py           # Просмотр/управление вакансиями
│   │   ├── sources_handler.py        # CRUD источников (ConversationHandler)
│   │   ├── settings_handler.py       # Настройки (промпты, бюджет, фильтры, авто-режим)
│   │   └── profile_handler.py        # Профиль фрилансера (ConversationHandler)
│   └── keyboards.py                  # Все клавиатуры (Reply + Inline)
│
├── services/                         # Бизнес-логика
│   ├── job_analyzer.py               # AI-анализ (OpenAI)
│   ├── response_generator.py         # AI-генерация откликов (OpenAI)
│   ├── monitor.py                    # Мониторинг источников
│   ├── sender.py                     # Отправка сообщений (Telethon)
│   ├── filters.py                    # Двухуровневая фильтрация (Pre + Post)
│   ├── blacklist.py                  # Blacklist service (NEW v2.1)
│   ├── rate_limiter.py               # Rate limiting (Kwork)
│   ├── llm_fallback.py               # Ollama fallback
│   └── logger_config.py              # structlog конфигурация
│
├── parsers/                          # Парсеры источников
│   ├── base.py                       # Базовый класс (ABC)
│   ├── kwork.py                      # Kwork v2 (Playwright + stealth)
│   ├── kwork_old.py                  # Старый парсер (deprecated)
│   └── telegram_source.py            # Telegram (Telethon)
│
├── db/                               # Персистентность
│   ├── models.py                     # Dataclass модели
│   ├── queries.py                    # Все SQL-запросы (CRUD)
│   └── init_db.py                    # Инициализация + миграции
│
├── tests/unit/                       # Unit-тесты
│   ├── test_filters.py
│   ├── test_parsers.py
│   └── test_analyzer.py
│
├── config.py                         # Конфигурация (из .env)
├── main.py                           # Точка входа + scheduler + handlers
├── requirements.txt                  # Зависимости
├── Dockerfile                        # Контейнеризация
├── docker-compose.yml                # Compose
├── .env.example                      # Шаблон переменных окружения
├── .gitignore
├── README.md                         # Документация
└── PROJECT_FULL.md                   # Полное описание (v2.0)
```

---

## 3. Модели данных (db/models.py)

### 3.1 JobVacancy
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
    skills: Optional[str] = None          # JSON list
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
```

### 3.2 Source
```python
@dataclass
class Source:
    id: Optional[int]
    name: str
    source_type: str                      # 'kwork', 'telegram'
    url: Optional[str]
    enabled: bool = True
    created_at: Optional[datetime] = None
```

### 3.3 UserSettings
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

### 3.4 FreelancerProfile
```python
@dataclass
class FreelancerProfile:
    id: Optional[int]
    user_id: int
    skills: Optional[str] = None
    experience_years: Optional[int] = None
    preferred_categories: Optional[str] = None
    hourly_rate: Optional[int] = None
    portfolio_url: Optional[str] = None
    bio: Optional[str] = None
    strong_sides: Optional[str] = None
    min_budget: Optional[int] = None
    max_budget: Optional[int] = None
    min_customer_rating: Optional[float] = None
    max_proposals_count: Optional[int] = None
    whitelist_words: Optional[str] = None
    blacklist_words: Optional[str] = None
    auto_mode_enabled: bool = False
    auto_mode_delay_minutes: int = 5
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

### 3.5 Response
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

### 3.6 ChatCooldown
```python
@dataclass
class ChatCooldown:
    id: Optional[int]
    chat_id: str
    last_sent_at: datetime
    cooldown_seconds: int
```

### 3.7 Blacklist (NEW v2.1)
```python
@dataclass
class Blacklist:
    id: Optional[int]
    entity_type: str                     # 'vacancy' or 'customer'
    entity_id: str                       # kwork_id or customer identifier
    reason: Optional[str]
    added_at: datetime
    user_id: int
```

---

## 4. Схема базы данных (db/init_db.py)

### Таблица `vacancies`
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PRIMARY KEY | ID |
| kwork_id | TEXT UNIQUE NOT NULL | ID проекта |
| url | TEXT NOT NULL | URL |
| title | TEXT NOT NULL | Заголовок |
| description | TEXT NOT NULL | Описание |
| budget | TEXT | Бюджет (текст) |
| budget_min | INTEGER | Мин. бюджет |
| budget_max | INTEGER | Макс. бюджет |
| deadline | TEXT | Срок (текст) |
| deadline_days | INTEGER | Срок (дни) |
| category | TEXT | Категория |
| subcategory | TEXT | Подкатегория |
| skills | TEXT | Навыки (JSON) |
| proposals_count | INTEGER | Количество предложений |
| customer_rating | REAL | Рейтинг заказчика |
| customer_orders | INTEGER | Заказы заказчика |
| source | TEXT NOT NULL DEFAULT 'kwork' | Источник |
| fetched_at | TEXT NOT NULL | Дата получения |
| analyzed | INTEGER NOT NULL DEFAULT 0 | Проанализирована |
| responded | INTEGER NOT NULL DEFAULT 0 | Откликнуто |
| ai_score | INTEGER | AI-оценка (0-100) |
| ai_priority | TEXT | Приоритет |
| ai_risks | TEXT | Риски |
| match_percentage | INTEGER | Процент совпадения |
| filtered_out | INTEGER NOT NULL DEFAULT 0 | Отфильтрована |
| filter_reason | TEXT | Причина фильтрации |

### Таблица `sources`
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PRIMARY KEY | ID |
| name | TEXT NOT NULL | Название |
| source_type | TEXT NOT NULL | Тип ('kwork', 'telegram') |
| url | TEXT | URL |
| enabled | INTEGER NOT NULL DEFAULT 1 | Включён |
| created_at | TEXT NOT NULL | Дата создания |

### Таблица `user_settings`
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PRIMARY KEY | ID |
| user_id | INTEGER NOT NULL UNIQUE | Telegram user ID |
| analysis_prompt | TEXT | Промпт для анализа |
| response_prompt | TEXT | Промпт для откликов |
| min_budget | INTEGER | Мин. бюджет |
| max_budget | INTEGER | Макс. бюджет |
| cooldown_seconds | INTEGER NOT NULL DEFAULT 3600 | Кулдаун |
| created_at | TEXT NOT NULL | Дата создания |
| updated_at | TEXT NOT NULL | Дата обновления |

### Таблица `freelancer_profile`
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PRIMARY KEY | ID |
| user_id | INTEGER NOT NULL UNIQUE | Telegram user ID |
| skills | TEXT | Навыки (JSON) |
| experience_years | INTEGER | Опыт (лет) |
| preferred_categories | TEXT | Предпочтительные категории (JSON) |
| hourly_rate | INTEGER | Ставка (руб/час) |
| portfolio_url | TEXT | Портфолио |
| bio | TEXT | О себе |
| strong_sides | TEXT | Сильные стороны |
| min_budget | INTEGER | Мин. бюджет |
| max_budget | INTEGER | Макс. бюджет |
| min_customer_rating | REAL | Мин. рейтинг заказчика |
| max_proposals_count | INTEGER | Макс. предложений |
| whitelist_words | TEXT | Белый список (JSON) |
| blacklist_words | TEXT | Чёрный список (JSON) |
| auto_mode_enabled | INTEGER NOT NULL DEFAULT 0 | Авто-режим |
| auto_mode_delay_minutes | INTEGER NOT NULL DEFAULT 5 | Задержка авто-режима |
| created_at | TEXT NOT NULL | Дата создания |
| updated_at | TEXT NOT NULL | Дата обновления |

### Таблица `responses`
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PRIMARY KEY | ID |
| vacancy_id | INTEGER NOT NULL | FK на vacancy |
| kwork_id | TEXT NOT NULL | ID проекта |
| response_text | TEXT NOT NULL | Текст отклика |
| approved | INTEGER NOT NULL DEFAULT 0 | Одобрен |
| sent | INTEGER NOT NULL DEFAULT 0 | Отправлен |
| created_at | TEXT NOT NULL | Дата создания |
| sent_at | TEXT | Дата отправки |

### Таблица `chat_cooldowns`
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PRIMARY KEY | ID |
| chat_id | TEXT NOT NULL UNIQUE | ID чата |
| last_sent_at | TEXT NOT NULL | Последняя отправка |
| cooldown_seconds | INTEGER NOT NULL | Кулдаун (сек) |

### Таблица `blacklist` (NEW v2.1)
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PRIMARY KEY | ID |
| entity_type | TEXT NOT NULL | Тип ('vacancy', 'customer') |
| entity_id | TEXT NOT NULL | ID сущности |
| reason | TEXT | Причина |
| added_at | TEXT NOT NULL | Дата добавления |
| user_id | INTEGER NOT NULL | Кто добавил |
| UNIQUE(entity_type, entity_id) | | Уникальность |

### Индексы
```sql
idx_vacancies_kwork_id ON vacancies(kwork_id)
idx_vacancies_source ON vacancies(source)
idx_vacancies_analyzed ON vacancies(analyzed)
idx_vacancies_filtered_out ON vacancies(filtered_out)
idx_vacancies_ai_priority ON vacancies(ai_priority)
idx_responses_vacancy_id ON responses(vacancy_id)
idx_responses_approved ON responses(approved)
idx_chat_cooldowns_chat_id ON chat_cooldowns(chat_id)
idx_freelancer_profile_user_id ON freelancer_profile(user_id)
idx_blacklist_entity ON blacklist(entity_type, entity_id)
```

---

## 5. Конфигурация (config.py)

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
| `KWORK_MAX_DETAIL_PAGES` | Макс. детальных страниц | `8` |
| `MONITOR_INTERVAL_MINUTES` | Интервал мониторинга | `15` |
| `DEFAULT_COOLDOWN_SEC` | Кулдаун по умолчанию | `3600` |

### Константы
| Константа | Значение |
|-----------|----------|
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `USER_AGENT` | Chrome 120 |

---

## 6. Зависимости (requirements.txt)

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

## 7. Все функции по модулям

### 7.1 db/queries.py

**Vacancies:**
| Функция | Описание |
|---------|----------|
| `is_vacancy_seen(db, kwork_id)` | Проверка дедупликации |
| `save_vacancy(db, vacancy)` | Сохранение вакансии |
| `update_vacancy_ai_analysis(db, kwork_id, ...)` | Обновление AI-полей |
| `mark_vacancy_filtered(db, kwork_id, reason)` | Пометка как отфильтрованной |
| `get_unseen_vacancies(db, limit)` | Новые неанализированные |
| `get_high_priority_vacancies(db, limit)` | High priority |
| `mark_vacancy_analyzed(db, kwork_id)` | Пометка проанализированной |
| `mark_vacancy_responded(db, kwork_id)` | Пометка откликнутой |
| `get_vacancy_by_kwork_id(db, kwork_id)` | Получение по ID |
| `get_vacancy_stats(db)` | Статистика |

**Sources:**
| Функция | Описание |
|---------|----------|
| `add_source(db, source)` | Добавление |
| `get_enabled_sources(db)` | Включённые |
| `get_all_sources(db)` | Все |
| `toggle_source(db, source_id)` | Вкл/выкл |
| `delete_source(db, source_id)` | Удаление |

**User Settings:**
| Функция | Описание |
|---------|----------|
| `get_user_settings(db, user_id)` | Получение |
| `save_user_settings(db, settings)` | Сохранение/обновление |

**Freelancer Profile:**
| Функция | Описание |
|---------|----------|
| `get_freelancer_profile(db, user_id)` | Получение |
| `save_freelancer_profile(db, profile)` | Сохранение/обновление |

**Responses:**
| Функция | Описание |
|---------|----------|
| `save_response(db, response)` | Сохранение |
| `approve_response(db, response_id)` | Одобрение |
| `get_response_by_id(db, response_id)` | По ID |
| `get_recent_responses(db, limit)` | Последние |
| `mark_response_sent(db, response_id)` | Отправка |

**Chat Cooldown:**
| Функция | Описание |
|---------|----------|
| `get_chat_cooldown(db, chat_id)` | Получение |
| `update_chat_cooldown(db, chat_id, cooldown)` | Обновление |
| `can_send_to_chat(db, chat_id, cooldown)` | Проверка |

**Blacklist (NEW v2.1):**
| Функция | Описание |
|---------|----------|
| `is_blacklisted(db, entity_type, entity_id)` | Проверка |
| `add_to_blacklist(db, entity_type, entity_id, user_id, reason)` | Добавление (UPSERT) |
| `remove_from_blacklist(db, entity_type, entity_id)` | Удаление |
| `get_blacklist(db, entity_type)` | Список |

---

### 7.2 services/blacklist.py (NEW v2.1)

```python
class BlacklistService:
    def __init__(self, db_path: str)
    
    async def is_blacklisted(entity_type, entity_id) -> bool
    async def add_to_blacklist(entity_type, entity_id, user_id, reason=None) -> None
    async def remove_from_blacklist(entity_type, entity_id) -> None
    async def get_blacklist(entity_type=None) -> List[Blacklist]
    async def check_vacancy(kwork_id, customer_id=None) -> bool
```

---

### 7.3 services/filters.py

```python
class VacancyFilter:
    def __init__(self, profile: Optional[FreelancerProfile] = None)
    
    async def apply_pre_filters(vacancy) -> (bool, Optional[str])  # Level 1
    def apply_post_filters(vacancy) -> (bool, Optional[str])       # Level 2
    
    def _get_blacklist() -> List[str]
    def _get_whitelist() -> List[str]
```

**Pre-filters (Level 1):**
1. Blacklist check (vacancy + customer)
2. Budget filter (min/max)
3. Blacklist words
4. Whitelist words
5. Customer rating
6. Max proposals

**Post-filters (Level 2):**
1. AI score < 30
2. Match percentage < 20

---

### 7.4 services/monitor.py

```python
class MonitorService:
    def __init__(self)
    
    async def check_all_sources() -> int
    async def _check_kwork(db, filter_engine) -> (int, int)
    async def _check_telegram(db, channel_url, filter_engine) -> (int, int)
    async def cleanup() -> None
```

---

### 7.5 services/job_analyzer.py

```python
class JobAnalyzer:
    def __init__(self)
    
    async def analyze_job(vacancy, custom_prompt=None, profile=None) -> Dict
    async def extract_price_range(text) -> Optional[Dict]
```

**AI Analysis Result:**
```json
{
    "suitable": bool,
    "score": int (0-100),
    "priority": "low" | "medium" | "high",
    "reason": str,
    "extracted_budget": str,
    "extracted_deadline": str,
    "complexity": str,
    "skills_required": list[str],
    "suggested_price": int,
    "risks": str,
    "match_percentage": int (0-100)
}
```

---

### 7.6 services/response_generator.py

```python
class ResponseGenerator:
    def __init__(self)
    
    async def generate_response(vacancy, custom_prompt=None, profile=None, recent_responses=None) -> Optional[str]
```

---

### 7.7 services/sender.py

```python
class SenderService:
    def __init__(self)
    
    async def send_message(chat_id, message, cooldown_seconds=None) -> bool
    async def get_remaining_cooldown(chat_id) -> Optional[int]
    async def cleanup() -> None
```

---

### 7.8 services/rate_limiter.py

```python
class KworkRateLimiter:
    def __init__(self, daily_limit=200, delay_min=2.0, delay_max=5.0, night_delay_multiplier=2.0)
    
    def can_make_request() -> bool
    def record_request() -> None
    def get_delay() -> float
    async def sleep() -> None
    def get_status() -> dict
```

---

### 7.9 services/llm_fallback.py

```python
class LLMFallback:
    def __init__(self, base_url="http://localhost:11434", model="llama3.2")
    
    async def is_available() -> bool
    async def analyze_job(vacancy, profile=None) -> Dict
    async def generate_response(vacancy, profile=None) -> Optional[str]
    async def close() -> None

async def get_llm_client() -> Optional[LLMFallback]
```

---

### 7.10 services/logger_config.py

```python
def configure_logging() -> None
def get_logger(name: str)
```

---

### 7.11 parsers/base.py

```python
class BaseParser(ABC):
    async def fetch_vacancies() -> List[JobVacancy]
    async def fetch_project_list() -> List[str]
    async def fetch_project_detail(url: str) -> JobVacancy
```

---

### 7.12 parsers/kwork.py (v2 — переписан)

```python
class KworkParser(BaseParser):
    def __init__(self, max_detail_pages=8)
    
    # Stealth helpers
    def _get_stealth_headers(referer=None) -> dict
    def _get_browser_context_args() -> dict
    async def _apply_stealth(page)
    async def _block_unnecessary_requests(page)
    async def _save_html_for_debug(page, filename)
    async def _setup_page(page, referer=None)
    async def _human_scroll(page)
    
    # Public API
    async def fetch_vacancies(limit=10) -> List[JobVacancy]  # Single browser
    async def fetch_project_list() -> List[str]              # Backward compat
    async def fetch_project_detail(url, basic_info=None) -> Optional[JobVacancy]  # Standalone
    
    # Internal
    async def _fetch_project_cards(context) -> List[dict]
    async def _fetch_detail_from_context(context, url, basic_info=None) -> Optional[JobVacancy]
    
    # Card parsing
    def _parse_list_card(card_el) -> Optional[dict]
    def _build_vacancy_from_card(card) -> Optional[JobVacancy]
    
    # Blocking detection
    def _is_blocked(soup) -> bool
    
    # JSON extraction
    def _extract_json_data(soup) -> Optional[dict]
    def _deep_search(data, keys, expected_type) -> Optional[Any]
    
    # Extractors (resilient: selectors -> regex -> None)
    def _extract_title(soup) -> Optional[str]
    def _extract_description(soup) -> Optional[str]
    def _extract_budget_text(soup) -> Optional[str]
    def _extract_budget_range(soup, budget_text) -> Tuple
    def _extract_budget_range_from_text(text) -> Tuple
    def _extract_deadline_text(soup) -> Optional[str]
    def _extract_deadline_days(deadline_text) -> Optional[int]
    def _extract_category(soup) -> Optional[str]
    def _extract_subcategory(soup) -> Optional[str]
    def _extract_skills(soup, description=None, json_data=None) -> Optional[List[str]]
    def _extract_proposals_count(soup) -> Optional[int]
    def _extract_customer_rating(soup) -> Optional[float]
    def _extract_customer_orders(soup) -> Optional[int]
```

**Stealth:**
- 5 USER_AGENTS
- 5 VIEWPORTS
- 3 ACCEPT_LANGUAGES
- 6 STEALTH_SCRIPTS (navigator.webdriver, chrome.runtime, plugins, languages, Notification, iframe)
- page.route: BLOCKED_RESOURCE_TYPES (image, media, font) + BLOCKED_URL_PATTERNS (analytics)
- --disable-blink-features=AutomationControlled

---

### 7.13 parsers/telegram_source.py

```python
class TelegramSourceParser(BaseParser):
    def __init__(self, session_name="freelance_radar_session")
    
    async def connect() -> None
    async def disconnect() -> None
    async def fetch_vacancies() -> List[JobVacancy]
    async def fetch_project_list() -> List[str]
    async def fetch_project_detail(url) -> Optional[JobVacancy]
    
    async def fetch_messages_from_channel(channel_username, limit=20) -> List[JobVacancy]
    def _message_to_vacancy(message, channel_username) -> Optional[JobVacancy]
    
    # Extractors
    def _extract_budget_from_text(text) -> Optional[str]
    def _extract_budget_range(text) -> tuple
    def _extract_deadline_from_text(text) -> Optional[str]
    def _extract_deadline_days(text) -> Optional[int]
    def _extract_category_from_text(text) -> Optional[str]
    def _extract_skills_from_text(text) -> Optional[List[str]]
    def _extract_contacts_from_text(text) -> Optional[str]
    
    async def send_message_to_chat(chat_id, message) -> bool
```

---

### 7.14 main.py

**Команды:**
| Команда | Описание |
|---------|----------|
| `/start` | Запуск бота |
| `/help` | Справка |
| `/check` | Ручная проверка |
| `/health` | Статус системы |
| `/stats` | Статистика вакансий |

**Ключевые функции:**
| Функция | Описание |
|---------|----------|
| `start()` | Приветствие + главное меню |
| `help_command()` | Справка |
| `check_sources_command()` | Ручная проверка |
| `health_command()` | Статус системы (Kwork rate, БД, ошибки) |
| `stats_command()` | Статистика (total, unseen, responded, filtered, high) |
| `refresh_stats()` | Обновление статистики |
| `handle_menu_buttons()` | Обработка главного меню |
| `handle_back_to_main()` | Назад в главное меню |
| `handle_settings_menu()` | Назад в настройки |
| `scheduled_check()` | Периодическая проверка (APScheduler) |
| `notify_new_vacancy()` | Отправка уведомления (HTML) |
| `check_monitor_health()` | Проверка здоровья мониторинга |
| `_format_vacancy_notification()` | Форматирование HTML-уведомления |

**scheduler.check_all_sources:**
1. `monitor.check_all_sources()` — парсинг
2. `queries.get_unseen_vacancies()` — новые
3. `analyzer.analyze_job()` — AI-анализ
4. `queries.update_vacancy_ai_analysis()` — сохранение результатов
5. `filter_engine.apply_post_filters()` — пост-фильтрация
6. `notify_new_vacancy()` — уведомление

**notify_new_vacancy:**
1. Проверка blacklist (BlacklistService)
2. Форматирование HTML
3. `bot.send_message()` с quick actions keyboard

---

## 8. Клавиатуры (bot/keyboards.py)

| Функция | Тип | Кнопки |
|---------|-----|--------|
| `main_menu_keyboard()` | Reply | Вакансии, Настройки, Источники, Статистика, Профиль, Помощь |
| `sources_keyboard()` | Inline | Добавить, Список, Назад |
| `source_type_keyboard()` | Inline | Kwork, Telegram, Отмена |
| `source_actions_keyboard(id, enabled)` | Inline | Вкл/выкл, Удалить, Назад |
| `vacancy_keyboard(kwork_id)` | Inline | Подходит, Не подходит, Отклик, ЧС |
| `quick_vacancy_actions_keyboard(kwork_id, priority)` | Inline | Отклик, Подробнее, Отложить, Пропустить, ЧС |
| `response_keyboard(response_id, kwork_id)` | Inline | Показать текст, Отправить, Редактировать, Перегенерировать, Отложить, Отменить |
| `settings_keyboard()` | Inline | Промпт анализа, Промпт откликов, Бюджет, Кулдаун, Фильтры, Назад |
| `filters_settings_keyboard()` | Inline | Белый список, Чёрный список, Мин. рейтинг, Макс. предложений, Авто-режим, Назад |
| `profile_keyboard()` | Inline | Навыки, Опыт, Категории, Ставка, Сильные стороны, О себе, Портфолио, Назад |
| `auto_mode_keyboard()` | Inline | Включить, Выключить, Задержка, Назад |
| `confirm_keyboard(action)` | Inline | Да, Нет |
| `cancel_keyboard()` | Inline | Отмена |
| `stats_keyboard()` | Inline | Обновить, Назад |

---

## 9. Обработчики (bot/handlers/)

### 9.1 jobs_handler.py
| Функция | Callback pattern | Описание |
|---------|-----------------|----------|
| `jobs_menu()` | — | Показать меню вакансий |
| `show_vacancy()` | — | Показать вакансию (HTML) |
| `vacancy_suitable()` | `vacancy_suitable_` | Пометить подходящей |
| `vacancy_skip()` | `vacancy_skip_` | Пропустить |
| `vacancy_blacklist()` | `vacancy_blacklist_` | В blacklist (vacancy + customer) |
| `vacancy_detail()` | `vacancy_detail_` | Подробный просмотр |
| `vacancy_generate_response()` | `vacancy_generate_` | Сгенерировать отклик |
| `vacancy_defer()` | `vacancy_defer_` | Отложить на 30 мин |
| `vacancy_send()` | `vacancy_send_` | Быстрая отправка (high priority) |
| `response_copy()` | `response_copy_` | Копировать текст |
| `response_send()` | `response_send_` | Отправить |
| `response_edit()` | `response_edit_` | Редактировать |
| `response_defer()` | `response_defer_` | Отложить ответ |
| `response_mark_sent()` | `response_mark_sent_` | Пометить отправленным |
| `response_cancel()` | `response_cancel_` | Отменить |

### 9.2 sources_handler.py
| Функция | Callback pattern | Описание |
|---------|-----------------|----------|
| `sources_menu()` | — | Меню источников |
| `list_sources()` | `list_sources` | Список |
| `add_source_start()` | `add_source` | Начать добавление |
| `source_type_selected()` | `source_type_` | Выбор типа |
| `source_name_entered()` | — | Ввод названия |
| `source_url_entered()` | — | Ввод URL |
| `toggle_source()` | `toggle_source_` | Вкл/выкл |
| `delete_source()` | `delete_source_` | Удалить |

### 9.3 settings_handler.py
| Функция | Callback pattern | Описание |
|---------|-----------------|----------|
| `settings_menu()` | — | Меню настроек |
| `settings_analysis_prompt()` | `settings_analysis_prompt` | Промпт анализа |
| `settings_response_prompt()` | `settings_response_prompt` | Промпт откликов |
| `settings_budget()` | `settings_budget` | Бюджет |
| `settings_cooldown()` | `settings_cooldown` | Кулдаун |
| `filters_menu()` | `settings_filters` | Меню фильтров |
| `settings_whitelist()` | `settings_whitelist` | Белый список |
| `settings_blacklist()` | `settings_blacklist` | Чёрный список |
| `settings_min_rating()` | `settings_min_rating` | Мин. рейтинг |
| `settings_max_proposals()` | `settings_max_proposals` | Макс. предложений |
| `auto_mode_menu()` | `settings_auto_mode` | Авто-режим |
| `auto_mode_on()` | `auto_mode_on` | Включить |
| `auto_mode_off()` | `auto_mode_off` | Выключить |
| `settings_auto_delay()` | `auto_mode_delay` | Задержка |

### 9.4 profile_handler.py
| Функция | Callback pattern | Описание |
|---------|-----------------|----------|
| `profile_menu()` | — | Меню профиля |
| `profile_skills_start()` | `profile_skills` | Навыки |
| `profile_experience_start()` | `profile_experience` | Опыт |
| `profile_categories_start()` | `profile_categories` | Категории |
| `profile_hourly_rate_start()` | `profile_hourly_rate` | Ставка |
| `profile_strong_sides_start()` | `profile_strong_sides` | Сильные стороны |
| `profile_bio_start()` | `profile_bio` | О себе |
| `profile_portfolio_start()` | `profile_portfolio` | Портфолио |

---

## 10. Поток данных

```
APScheduler (каждые 15 мин)
  → MonitorService.check_all_sources()
    → KworkParser.fetch_vacancies() [Playwright + stealth, single browser]
      → _fetch_project_cards(context) → list page
      → _fetch_detail_from_context(context, url) → detail pages (top N)
    → TelegramSourceParser.fetch_messages_from_channel()
    → VacancyFilter.apply_pre_filters() [Level 1]
      → BlacklistService.check_vacancy() [NEW]
      → budget, blacklist words, whitelist, rating, proposals
      → db.is_vacancy_seen() — дедупликация
      → db.save_vacancy() — сохранение (или filtered_out)
    → Для неотфильтрованных:
      → JobAnalyzer.analyze_job() [OpenAI / Ollama fallback]
        → db.update_vacancy_ai_analysis()
      → VacancyFilter.apply_post_filters() [Level 2]
        → db.update_vacancy_ai_analysis()
        → notify_new_vacancy() → bot.send_message() [HTML]
          → BlacklistService.check_vacancy() [NEW]

Пользователь (через Telegram):
  → 📋 Вакансии → jobs_handler.show_vacancy()
  → 💬 Сгенерировать отклик → ResponseGenerator.generate_response()
    → с профилем + историей
  → ✅ Отправить → SenderService.send_message() [Telethon + кулдаун]
  → 🚫 Чёрный список → BlacklistService.add_to_blacklist()
```

---

## 11. Уведомления (HTML)

### Короткий формат (notification)
```
🔥 ВЫСОКИЙ • Score: 94/100 • Match: 89%
💰 20,000 – 30,000 ₽
⏳ 2 д. 23 ч. • 📊 4 предл. • ⭐ 4.9 (231)

<b>Сделать редизайн сайта</b>
Необходимо сделать редизайн сайта Medpool.pro...
🛠 Навыки: python, fastapi, postgresql, docker, react

🔗 Открыть на Kwork
```

### Подробный формат (detail view)
```
🔥 ВЫСОКИЙ • Score: 94/100 • Match: 89%
<b>Сделать редизайн сайта</b>
💰 20,000 – 30,000 ₽
⏳ 2 д. 23 ч. • 📅 3 дн. • 📊 4 предл. • ⭐ 4.9 (231 заказов)
📁 Дизайн

Необходимо сделать редизайн сайта Medpool.pro...
🛠 Навыки: python, fastapi, postgresql, docker, react

🔗 Открыть заказ
📡 kwork • ID: 3170568
```

### Кнопки (inline)
```
[💬 Отклик] [👀 Подробнее]
[⏳ Отложить] [⏭ Пропустить]
[🚫 В чёрный список]
```
Для high priority добавляется `🚀 Отправить`.

---

## 12. Что реализовано (v2.1)

| Функция | Статус |
|---------|--------|
| Telegram-бот | ✅ |
| Мониторинг Kwork v2 (stealth + single browser) | ✅ |
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
| Красивое отображение вакансий (HTML) | ✅ |
| Quick actions в уведомлениях | ✅ |
| Статистика /stats | ✅ |
| Health check /health | ✅ |
| Docker + docker-compose | ✅ |
| Self-hosted LLM fallback (Ollama) | ✅ |
| Миграции БД | ✅ |
| Retry (tenacity) | ✅ |
| structlog логирование | ✅ |
| Rate limiting Kwork (200/сутки) | ✅ |
| Blacklist service (vacancy + customer) | ✅ |
| Route blocking (analytics, ads, media) | ✅ |
| JSON extraction from <script> | ✅ |
| Skills from description (keyword extraction) | ✅ |
| Unit тесты | ✅ (32 теста) |
| E2E тесты | ❌ |
| Integration тесты | ❌ |

---

## 13. Изменения, внесённые в этом сеансе

| Файл | Что изменено |
|------|-------------|
| `parsers/kwork.py` | Полностью переписан (v3): single browser, route blocking, resilient selectors, JSON extraction, skills from description, `max_detail_pages` из config |
| `config.py` | Добавлен `KWORK_MAX_DETAIL_PAGES` |
| `services/logger_config.py` | Добавлена UTF-8 обёртка для StreamHandler (Windows) |
| `main.py` | `notify_new_vacancy()` → HTML parse_mode, `_format_vacancy_notification()` с html.escape, проверка blacklist |
| `bot/keyboards.py` | `quick_vacancy_actions_keyboard()` → 5 кнопок, conditional "🚀 Отправить" для high priority |
| `bot/handlers/jobs_handler.py` | `_format_vacancy_text()` → HTML, `show_vacancy()` → HTML, `vacancy_blacklist` → blacklist + customer, `vacancy_defer`, `vacancy_send`, все `parse_mode="HTML"` |
| `db/models.py` | Добавлена модель `Blacklist` |
| `db/init_db.py` | Добавлена таблица `blacklist` + индекс |
| `db/queries.py` | CRUD для blacklist: `is_blacklisted`, `add_to_blacklist`, `remove_from_blacklist`, `get_blacklist` |
| `services/blacklist.py` | **Новый** файл: `BlacklistService` с 5 методами |
| `services/filters.py` | `VacancyFilter.apply_pre_filters()` → async, проверка blacklist через `BlacklistService` |
| `services/monitor.py` | `await` добавлен перед `apply_pre_filters` (теперь async) |

---

---

# 14. Анализ слабых мест и рекомендации по улучшению

## Рейтинг текущего состояния: 7/10

Проект рабочий, модульный, хорошо структурированный. Но есть критические и некритические проблемы, которые мешают достичь идеала.

---

## 🔴 КРИТИЧЕСКИЕ ПРОБЛЕМЫ (нужно исправить)

### 14.1 Нет проверки `__init__` в базовых классах

**Проблема:** `BaseParser` — ABC, но `fetch_vacancies()` не принимает `limit`. А `KworkParser.fetch_vacancies(limit=10)` — принимает. Это нарушение Liskov Substitution.

**Решение:** Добавить `limit` как опциональный параметр в `BaseParser.fetch_vacancies()`.

### 14.2 `VacancyFilter.apply_pre_filters()` стал async, но в `scheduled_check()` его вызывают без `await`

**Проблема:** В `main.py` (строка 285) `filter_engine.apply_post_filters(vacancy)` — sync. Но `apply_pre_filters()` теперь async. Это может привести к тому, что pre-filters не работают.

**Решение:** Убедиться, что `apply_pre_filters()` вызывается с `await` везде. В `monitor.py` уже исправлено. Но в `scheduled_check()` нет вызова `apply_pre_filters` — он применяется в `monitor.py`.

### 14.3 SQLite — небезопасно для конкурентного доступа

**Проблема:** `aiosqlite` открывает соединение на каждый запрос. В многопоточной среде это может привести к гонке данных. SQLite не масштабируется.

**Решение:** Для MVP это допустимо. Для продакшена — PostgreSQL.

### 14.4 Нет обработки ошибок при изменении структуры HTML Kwork

**Проблема:** Парсер парсит реальный HTML, но если Kwork изменит классы, парсер сломается без уведомления. Нет мониторинга изменений.

**Решение:** Добавить алерт при нулевом количестве карточек, сохранять HTML для анализа.

### 14.5 Нет Rate Limiting для OpenAI API

**Проблема:** `JobAnalyzer` и `ResponseGenerator` не имеют rate limiting. При большом количестве вакансий можно получить rate limit.

**Решение:** Добавить `tenacity` с `wait_exponential` для OpenAI вызовов.

---

## 🟡 СРЕДНИЕ ПРОБЛЕМЫ (желательно исправить)

### 14.6 Нет TTL для blacklist

**Проблема:** Blacklist не имеет времени жизни. Заблокированные вакансии/заказчики остаются навсегда.

**Решение:** Добавить поле `expires_at` в таблицу `blacklist`. Или добавить команду `/blacklist` для просмотра и удаления.

### 14.7 Нет UI для управления blacklist

**Проблема:** Добавить в blacklist можно только через кнопку в уведомлении. Нет команды `/blacklist` для просмотра и удаления записей.

**Решение:** Добавить команду `/blacklist` с inline-кнопками для просмотра и удаления.

### 14.8 Auto-mode не интегрирован с scheduler

**Проблема:** `auto_mode_enabled` сохраняется в профиле, но нигде не используется. Авто-режим не работает.

**Решение:** В `scheduled_check()` проверять `auto_mode_enabled` и автоматически генерировать отклик для high-priority вакансий.

### 14.9 Нет пагинации для списка вакансий

**Проблема:** `/check` показывает только последние N вакансий. Нет навигации по страницам.

**Решение:** Добавить inline-кнопки "← Предыдущая" / "Следующая →" для навигации по вакансиям.

### 14.10 Нет валидации входных данных

**Проблема:** В settings_handler.py нет валидации для числовых полей. Пользователь может ввести что угодно.

**Решение:** Добавить валидацию (например, `min_budget > 0`, `cooldown_seconds > 60`).

### 14.11 Нет graceful shutdown

**Проблема:** При SIGTERM бот не корректно завершает работу. Playwright может остаться открытым.

**Решение:** Добавить обработчик сигнала и корректное закрытие.

### 14.12 `kwork_old.py` не удалён

**Проблема:** Старый парсер всё ещё в проекте. Это может запутать.

**Решение:** Удалить или переместить в архив.

---

## 🟢 НЕКРИТИЧЕСКИЕ ПРОБЛЕМЫ (можно улучшить)

### 14.13 Нет документов для деплоя

**Проблема:** README.md не содержит инструкций по Docker-деплою. Dockerfile есть, но нет документации.

**Решение:** Расширить README с инструкциями по Docker.

### 14.14 Нет health check для Playwright

**Проблема:** Если Chromium не установлен, бот падает без понятного сообщения.

**Решение:** Добавить проверку `playwright install chromium` при старте.

### 14.15 Нет мониторинга стоимости OpenAI API

**Проблема:** Каждый анализ — это ~$0.001-0.003. Нет трекинга расходов.

**Решение:** Добавить трекинг токенов и стоимость в логи.

### 14.16 Нет логирования длительности запросов

**Проблема:** Нет метрик времени выполнения парсинга и анализа.

**Решение:** Добавить `timing` логи.

### 14.17 Нет unit-тестов для blacklist

**Проблема:** Добавлен новый модуль `services/blacklist.py`, но нет тестов.

**Решение:** Написать тесты для `BlacklistService`.

### 14.18 Нет unit-тестов для jobs_handler

**Проблема:** Тесты есть для `test_filters`, `test_parsers`, `test_analyzer`, но нет для jobs_handler.

**Решение:** Написать тесты для обработчиков.

### 14.19 Нет README с описанием архитектуры

**Проблема:** README.md поверхностный. Нет описания архитектуры, потока данных.

**Решение:** Расширить README.

### 14.20 Нет `.env.example` с `KWORK_MAX_DETAIL_PAGES`

**Проблема:** Добавлена новая переменная, но `.env.example` не обновлён.

**Решение:** Добавить `KWORK_MAX_DETAIL_PAGES=8` в `.env.example`.

---

## 15. Рекомендации для достижения 10/10

### Приоритет 1 (Критично — нужно сделать сейчас):

| # | Действие | Ожидаемый результат |
|---|----------|-------------------|
| 1 | Исправить `BaseParser.fetch_vacancies()` — добавить `limit` параметр | Корректная Liskov substitution |
| 2 | Добавить rate limiting для OpenAI (tenacity + wait_exponential) | Защита от rate limit |
| 3 | Добавить `expires_at` в blacklist + команду `/blacklist` | Управление blacklist |
| 4 | Интегрировать auto-mode с scheduler | Автоматические отклики |
| 5 | Удалить `kwork_old.py` | Чистота кода |
| 6 | Обновить `.env.example` с `KWORK_MAX_DETAIL_PAGES` | Корректная документация |
| 7 | Написать unit-тесты для `BlacklistService` | Покрытие тестами |

### Приоритет 2 (Важно — сделать в ближайшее время):

| # | Действие | Ожидаемый результат |
|---|----------|-------------------|
| 8 | Добавить пагинацию для списка вакансий | Удобная навигация |
| 9 | Добавить валидацию входных данных | Защита от некорректных данных |
| 10 | Добавить graceful shutdown | Корректное завершение |
| 11 | Добавить мониторинг длительности запросов | Метрики производительности |
| 12 | Расширить README с инструкциями по деплою | Документация |
| 13 | Добавить проверку Playwright при старте | Устойчивость |

### Приоритет 3 (Желательно — сделать позже):

| # | Действие | Ожидаемый результат |
|---|----------|-------------------|
| 14 | Перейти на PostgreSQL | Масштабируемость |
| 15 | Добавить трекинг стоимости OpenAI | Контроль расходов |
| 16 | Добавить unit-тесты для jobs_handler | Покрытие тестами |
| 17 | Добавить мониторинг изменений HTML Kwork | Устойчивость парсера |
| 18 | Добавить прокси для Kwork | Стабильность |

---

## 16. Финальная оценка

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| **Архитектура** | 8/10 | Модульная, чистая, но нет разделения на пакеты |
| **Код** | 7/10 | Хороший стиль, но нет type hints везде, нет docstrings |
| **Тесты** | 5/10 | 32 теста, но нет тестов для handlers, blacklist, monitor |
| **Документация** | 6/10 | README поверхностный, нет API-документации |
| **Безопасность** | 7/10 | Есть rate limiting, но нет защиты от CSRF |
| **Производительность** | 7/10 | Playwright может быть медленным, нет кэширования |
| **Устойчивость** | 6/10 | Stealth работает, но нет мониторинга изменений |
| **UX** | 8/10 | Красивые уведомления, HTML, inline-кнопки |
| **Деплой** | 7/10 | Docker есть, но нет инструкций |
| **Общая оценка** | **7/10** | Рабочий MVP, но нужна доработка |

### Итого: 7/10

Проект — это **рабочий MVP** с хорошей архитектурой, но с множеством мелких проблем, которые нужно решить для достижения 10/10.

---

*Документ создан: 2026-05-07*
*Версия: v2.1*
*Состояние: Финальный апгрейд*
