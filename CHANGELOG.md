# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Phase 1: Architecture**
  - DI-container (`services/dependencies.py`) — ServiceRegistry with singletons, factories, overrides
  - AuthMiddleware (`bot/middleware.py`) — authorization middleware for python-telegram-bot
  - EventBus integration — events published on all pipeline stages
  - Metrics middleware in main.py

- **Phase 2: Performance**
  - AI Cache (`services/ai_cache.py`) — LRU cache with TTL for OpenAI responses
  - Batch analysis (`services/job_analyzer.py`) — `analyze_jobs()` with semaphore (max 5 concurrent)
  - Batch DB operations (`db/queries.py`) — `batch_save_vacancies()`, `batch_update_vacancy_ai_analysis()`
  - Database connection manager (`db/database.py`) — WAL mode, connection pooling
  - Optimized scheduler — parallel analysis, single JobAnalyzer instance

- **Phase 4: UI/UX**
  - Full-text search (`/search <query>`) with FTS5 in SQLite
  - Chart generation (`/chart`) — 4 chart types (pie, bar, line)
  - Inline keyboards — already implemented (quick_vacancy_actions, pagination)
  - Charts service (`services/charts.py`) — matplotlib integration

- **Phase 5: Monitoring**
  - Extended metrics (`services/metrics.py`) — Counter, Gauge, Histogram, Timer + Prometheus export
  - Tracing (`services/tracing.py`) — span-based tracing with context managers
  - Alerting (`services/alerting.py`) — alert rules with cooldown, 4 default rules
  - EventBus events — CHECK_STARTED, VACANCIES_FETCHED, VACANCY_ANALYZED, etc.

- **Phase 6: DevOps**
  - CI/CD workflow (`.github/workflows/ci.yml`) — lint, test, coverage, security, build
  - Docker improvements — entrypoint script, healthcheck
  - Docker Compose — resource limits, stop_grace_period
  - Logging with `RotatingFileHandler` — 10MB, 5 backups

- **Phase 7: Code**
  - Replaced 37/39 `except Exception` with specific types
  - Fixed Python 3.10 compatibility (Optional, List, Tuple, Dict)
  - Updated pytest/pytest-asyncio to compatible versions
  - Added `PRIORITY_MAP` to constants.py
  - Tests: 142 tests passing

- **Phase 8: Documentation**
  - Updated README.md with full architecture and usage documentation
  - Created CHANGELOG.md

## [v2.1] — 2024-01-01

### Initial release
- Telegram bot for monitoring freelance platforms
- Kwork parser with Playwright + stealth
- Telegram source parser with Telethon
- AI analysis with OpenAI GPT-4o-mini
- Two-level filtering (pre + post)
- Response generation
- SQLite database
- Docker support
- Basic tests

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/):
- **Major** (X.0.0): Breaking changes
- **Minor** (0.X.0): New features (backward compatible)
- **Patch** (0.0.X): Bug fixes

## How to update

1. Pull latest changes: `git pull`
2. Install dependencies: `pip install -r requirements.txt`
3. Run migrations: `python db/init_db.py`
4. Restart the bot: `python main.py` or `docker compose up -d`
