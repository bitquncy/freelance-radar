# Changelog

## [2.1.0] - 2026-07-28

### ⚡ Производительность
- **Оптимизация Playwright**: Браузер теперь переиспользуется между циклами проверки вместо создания нового на каждый fetch. Экономия ~500MB RAM и ~5 сек на цикл.
- **Persistent browser connection**: Добавлен `_get_browser()` с автоматическим восстановлением при обрыве.
- **Cleanup ресурсов**: `MonitorService.cleanup()` теперь корректно закрывает и KworkParser.

### 🐛 Исправление критических ошибок
- **Missing keyboards**: Добавлены `tg_analysis_keyboard`, `kwork_filters_keyboard`, `ai_friendly_filter_keyboard` — чинят runtime ошибки в TG Analysis и Kwork Filters.
- **Missing queries**: Реализованы функции для broadcast: `create_chat_group`, `get_chat_groups`, `get_chat_group`, `get_chat_group_members`, `add_chat_to_group`, `delete_chat_group`, `save_broadcast`, `get_broadcast_history`, `get_vacancies_by_source`.
- **Missing tables**: Добавлены таблицы `chat_groups`, `chat_group_members`, `broadcasts` в `init_db.py`.
- **Тесты**: 12 тестов падали с `OpenAIError` — исправлено через `tests/conftest.py`.
- **except Exception**: Заменён на конкретные типы в broadcast_handler.
- **Синтаксические ошибки**: Исправлены слипшиеся строки в `group_selected` и `receive_broadcast_message`.

### 🔒 Безопасность
- **FTS5 injection**: Усилено экранирование поисковых запросов через санитизацию regex.
- **@owner_only**: Добавлен на все state handler функции в profile_handler (defense-in-depth).
- **save_broadcast user_id**: Исправлена вставка `user_id=0` — теперь передаётся `OWNER_CHAT_ID`.

### 🚀 Улучшения
- **Rate limiting broadcast**: Добавлена задержка 0.5s между отправками сообщений в рассылке.
- **Scheduler lock timeout**: Lock на проверку источников теперь имеет timeout 30s и auto-recovery.
- **Dead code**: Удалена неиспользуемая функция `_format_vacancy_text`.
- **Tuple indexing**: Broadcast handler переведён на tuple-индексы для работы с сырыми данными из queries.
- **Docker**: Добавлен `.dockerignore`, улучшена Production-ready конфигурация.
- **CI/CD**: env vars вынесены в глобальный `env:` блок, устранена избыточность.

### 📦 Изменения в файлах
- `bot/keyboards.py` — +3 новые клавиатуры
- `bot/handlers/broadcast_handler.py` — except Exception → specific types, rate limiting, tuple indexing
- `bot/handlers/profile_handler.py` — +7 @owner_only
- `bot/handlers/jobs_handler.py` — удалён dead code
- `parsers/kwork.py` — persistent browser, cleanup()
- `services/monitor.py` — cleanup kwork parser
- `services/scheduler.py` — lock timeout
- `db/queries.py` — +9 функций, фикс FTS5, save_broadcast user_id
- `db/init_db.py` — +3 таблицы
- `tests/conftest.py` — новый файл с env vars
- `.dockerignore` — новый файл
- `.github/workflows/ci.yml` — централизованные env vars

## [2.0.0] - 2026-07-01
- Первая стабильная версия
- Kwork парсер с Playwright
- Telegram парсер через t.me/s/
- AI анализ вакансий через OpenAI
- Система фильтров (уровни 1 и 2)
- Авто-режим для high-priority
- Графики статистики
- Чёрный список с TTL
