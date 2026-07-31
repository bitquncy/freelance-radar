"""Scheduler service for periodic monitoring and health checks."""
import asyncio
from datetime import datetime
from typing import List, Tuple

from telegram.error import TelegramError
from telegram.ext import Application

from services.logger_config import get_logger
from services.monitor import MonitorService
from services.job_analyzer import JobAnalyzer
from services.filters import VacancyFilter
from services.notifications import notify_new_vacancy
from services.blacklist import BlacklistService
from services.ai_cache import get_ai_cache
from services.event_bus import get_event_bus, Events
from services.tracing import get_tracer
from services.alerting import get_alerting
from services.metrics import get_metrics
from db import queries
from db.database import get_database
from db.models import JobVacancy
from config import DB_PATH, OWNER_CHAT_ID
from emoji_config import E

logger = get_logger(__name__)

# Get instances
_event_bus = get_event_bus()
_tracer = get_tracer()
_alerting = get_alerting()
_metrics = get_metrics()


class SchedulerState:
    """Shared state for scheduler (avoids module-level globals)."""

    def __init__(self):
        self.last_check_time: datetime = datetime.now()
        self.last_check_count: int = 0
        self.last_check_errors: List[str] = []
        self.is_checking: bool = False
        self._lock = asyncio.Lock()


_state = SchedulerState()


def get_state() -> SchedulerState:
    """Get scheduler state."""
    return _state


async def scheduled_check(application: Application) -> None:
    """Scheduled job with streaming notifications — each vacancy sent immediately."""
    await check_and_notify_streaming(application, is_scheduled=True)


async def check_and_notify_streaming(
    application: Application,
    is_scheduled: bool = False,
    progress_message=None,
) -> None:
    """Check sources and send notifications one by one as vacancies are found.

    Optimized flow:
    1. Fetch all vacancies from sources
    2. Pre-filter and batch-save to DB
    3. Batch analyze with parallel OpenAI requests (max 5 concurrent)
    4. Post-filter and notify

    Args:
        application: Telegram application
        is_scheduled: True if called from scheduler (not user command)
        progress_message: Optional message object to update progress
    """
    # Try to acquire lock with timeout to prevent hanging
    try:
        await asyncio.wait_for(_state._lock.acquire(), timeout=30.0)
    except asyncio.TimeoutError:
        logger.error("scheduler.lock_timeout", previous_check_stuck=True)
        _state.is_checking = False
        _state._lock = asyncio.Lock()  # Reset lock
        await _state._lock.acquire()

    if _state.is_checking:
        _state._lock.release()
        logger.info("scheduler.already_checking")
        return
    _state.is_checking = True
    _state._lock.release()

    logger.info("scheduler.check_started")
    _state.last_check_time = datetime.now()
    _state.last_check_errors = []

    await _event_bus.publish(Events.CHECK_STARTED, {"is_scheduled": is_scheduled})

    # Start tracing span
    _metrics.gauge("scheduler.is_checking").set(1)

    monitor = MonitorService()
    analyzer = JobAnalyzer()  # Reuse single instance
    db = get_database()

    try:
        async with db.connection() as conn:
            settings = await queries.get_user_settings(conn, OWNER_CHAT_ID)
            profile = await queries.get_freelancer_profile(conn, OWNER_CHAT_ID)
            filter_engine = VacancyFilter(profile)

        # Step 1: Fetch vacancies from all sources
        if progress_message:
            try:
                await progress_message.edit_text(f"{E.RELOAD} Получаю вакансии...")
            except (TelegramError, ValueError, TypeError):
                pass

        with _tracer.span("fetch_vacancies") as span:
            raw_vacancies = await monitor.fetch_all_vacancies()
            raw_count = len(raw_vacancies)
            span.set_attribute("vacancies_count", raw_count)
            _metrics.counter("vacancies_fetched_total").inc(raw_count)

        await _event_bus.publish(Events.VACANCIES_FETCHED, {"count": raw_count})

        if raw_count == 0:
            if progress_message:
                await progress_message.edit_text("\u2705 Новых вакансий нет.")
            return

        if progress_message:
            try:
                await progress_message.edit_text(
                    f"\u26a1 Найдено {raw_count} вакансий. Фильтрую..."
                )
            except (TelegramError, ValueError, TypeError):
                pass

        # Step 2: Pre-filter and categorize
        new_vacancies: List[JobVacancy] = []
        filtered_vacancies: List[JobVacancy] = []
        seen_count = 0

        async with db.connection() as conn:
            # Batch check seen kwork_ids (N+1 fix)
            all_kwork_ids = [v.kwork_id for v in raw_vacancies]
            seen_ids = await queries.get_seen_kwork_ids(conn, all_kwork_ids)

            for vacancy in raw_vacancies:
                if vacancy.kwork_id in seen_ids:
                    seen_count += 1
                    continue

                keep, reason = await filter_engine.apply_pre_filters(vacancy)
                if not keep:
                    vacancy.filtered_out = True
                    vacancy.filter_reason = reason
                    filtered_vacancies.append(vacancy)
                    await _event_bus.publish(Events.VACANCY_PRE_FILTERED, {
                        "kwork_id": vacancy.kwork_id,
                        "reason": reason,
                    })
                else:
                    new_vacancies.append(vacancy)
                    await _event_bus.publish(Events.VACANCY_SAVED, {
                        "kwork_id": vacancy.kwork_id,
                        "title": vacancy.title[:50],
                    })

            # Batch save filtered vacancies
            if filtered_vacancies:
                await queries.batch_save_vacancies(conn, filtered_vacancies)

            # Batch save new vacancies
            if new_vacancies:
                await queries.batch_save_vacancies(conn, new_vacancies)

        new_count = len(new_vacancies)
        filtered_count = len(filtered_vacancies)

        if new_count == 0:
            summary = (
                f"\u2705 **Проверка завершена**\n\n"
                f"{E.PACKAGE} Получено: {raw_count}\n"
                f"{E.EYE} Уже видено: {seen_count}\n"
                f"{E.BAN} Отфильтровано: {filtered_count}\n"
                f"{E.NEW} Новых: 0"
            )
            if progress_message:
                await progress_message.edit_text(summary, parse_mode="Markdown")
            else:
                await application.bot.send_message(
                    chat_id=OWNER_CHAT_ID,
                    text=summary,
                    parse_mode="Markdown",
                )
            return

        if progress_message:
            try:
                await progress_message.edit_text(
                    f"\u26a1 Анализирую {new_count} вакансий..."
                )
            except (TelegramError, ValueError, TypeError):
                pass

        # Step 3: Batch analyze with parallel requests
        custom_prompt = settings.analysis_prompt if settings else None

        with _tracer.span("batch_analyze") as span:
            analyses = await analyzer.analyze_jobs(
                new_vacancies,
                custom_prompt=custom_prompt,
                profile=profile,
                max_concurrent=5,
            )
            span.set_attribute("vacancies_analyzed", len(analyses))
            _metrics.counter("vacancies_analyzed_total").inc(len(analyses))

        # Step 4: Post-filter, update DB, notify
        analyzed_count = 0
        high_priority_count = 0
        auto_mode_responses = 0

        ai_updates: List[Tuple] = []
        filtered_kwork_ids: List[Tuple] = []

        async with db.connection() as conn:
            for i, (vacancy, analysis) in enumerate(zip(new_vacancies, analyses)):
                # Update AI fields
                ai_updates.append((
                    analysis.get("score"),
                    analysis.get("priority"),
                    analysis.get("risks"),
                    analysis.get("match_percentage"),
                    vacancy.kwork_id,
                ))

                # Post-filter check
                vacancy.ai_score = analysis.get("score")
                vacancy.ai_priority = analysis.get("priority")
                vacancy.match_percentage = analysis.get("match_percentage")

                post_keep, post_reason = filter_engine.apply_post_filters(vacancy)
                if not post_keep:
                    filtered_kwork_ids.append((vacancy.kwork_id, post_reason))
                    continue

                analyzed_count += 1
                if analysis.get("priority") == "high":
                    high_priority_count += 1

                await _event_bus.publish(Events.VACANCY_ANALYZED, {
                    "kwork_id": vacancy.kwork_id,
                    "score": analysis.get("score"),
                    "priority": analysis.get("priority"),
                    "match": analysis.get("match_percentage"),
                })

                # Send notification
                with _tracer.span(f"notify_{vacancy.kwork_id}") as span:
                    await notify_new_vacancy(application, vacancy, analysis)
                    span.set_attribute("kwork_id", vacancy.kwork_id)
                    span.set_attribute("priority", analysis.get("priority"))
                    _metrics.counter("vacancies_notified_total").inc()

                await _event_bus.publish(Events.VACANCY_NOTIFIED, {
                    "kwork_id": vacancy.kwork_id,
                    "priority": analysis.get("priority"),
                })

                # Auto-mode for high priority
                if (
                    profile
                    and profile.auto_mode_enabled
                    and analysis.get("priority") == "high"
                ):
                    try:
                        from services.response_generator import ResponseGenerator
                        from db.models import Response

                        response_gen = ResponseGenerator()
                        response_text = await response_gen.generate_response(
                            vacancy, custom_prompt, profile
                        )
                        if response_text:
                            auto_mode_responses += 1
                            # Save response to DB
                            async with db.connection() as resp_conn:
                                vacancy_id = await queries.get_vacancy_id_by_kwork_id(
                                    resp_conn, vacancy.kwork_id
                                )
                                if vacancy_id:
                                    resp = Response(
                                        id=None,
                                        vacancy_id=vacancy_id,
                                        kwork_id=vacancy.kwork_id,
                                        response_text=response_text,
                                        approved=False,
                                        sent=False,
                                    )
                                    await queries.save_response(resp_conn, resp)
                            # Notify owner about auto-generated response
                            try:
                                import html as _html
                                notify_text = (
                                    f"{E.ROBOT} <b>Авто-ответ сгенерирован</b>\n\n"
                                    f"<b>{_html.escape(vacancy.title[:60])}</b>\n"
                                    f"Приоритет: {analysis.get('priority', 'medium')}\n\n"
                                    f"<pre>{_html.escape(response_text)}</pre>\n\n"
                                    f"Ответ сохранён. Отправьте вручную или используйте кнопки."
                                )
                                await application.bot.send_message(
                                    chat_id=OWNER_CHAT_ID,
                                    text=notify_text,
                                    parse_mode="HTML",
                                    disable_web_page_preview=True,
                                )
                            except (TelegramError, ValueError, TypeError):
                                pass

                            await _event_bus.publish(Events.AUTO_MODE_TRIGGERED, {
                                "kwork_id": vacancy.kwork_id,
                            })
                    except (ValueError, TypeError, ConnectionError, OSError, AttributeError) as e:
                        logger.error(
                            "scheduler.auto_mode_error",
                            kwork_id=vacancy.kwork_id,
                            error=str(e),
                        )

                # Update progress every 3 notifications
                if progress_message and (analyzed_count) % 3 == 0:
                    try:
                        await progress_message.edit_text(
                            f"\u26a1 Прогресс: {analyzed_count}/{new_count} "
                            f"(уведомлений отправлено)"
                        )
                    except (TelegramError, ValueError, TypeError):
                        pass

            # Batch update AI analysis fields
            if ai_updates:
                await queries.batch_update_vacancy_ai_analysis(conn, ai_updates)

            # Batch mark filtered
            if filtered_kwork_ids:
                await queries.batch_mark_vacancy_filtered(conn, filtered_kwork_ids)

        _state.last_check_count = new_count

        # Step 5: Summary
        summary = (
            f"\u2705 **Проверка завершена**\n\n"
            f"{E.PACKAGE} Получено: {raw_count}\n"
            f"{E.NEW} Новых: {new_count}\n"
            f"{E.BAN} Отфильтровано: {filtered_count + len(filtered_kwork_ids)}\n"
            f"{E.BELL} Уведомлений отправлено: {analyzed_count}\n"
            f"{E.RED} High priority: {high_priority_count}"
        )
        if auto_mode_responses > 0:
            summary += f"\n{E.ROBOT} Авто-ответы: {auto_mode_responses}"

        # Add cache stats
        cache_stats = get_ai_cache().get_stats()
        if cache_stats["size"] > 0:
            summary += f"\n{E.DISK} AI кэш: {cache_stats['size']} записей"

        if progress_message:
            await progress_message.edit_text(summary, parse_mode="Markdown")
        else:
            await application.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=summary,
                parse_mode="Markdown",
            )

        await _event_bus.publish(Events.CHECK_COMPLETED, {
            "raw_count": raw_count,
            "new_count": new_count,
            "filtered_count": filtered_count,
            "analyzed_count": analyzed_count,
            "high_priority_count": high_priority_count,
            "auto_mode_responses": auto_mode_responses,
        })

        if _state.last_check_errors and len(_state.last_check_errors) > 3:
            await application.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=f"\u26a0\ufe0f **Внимание**\n\nВ последней проверке произошло {len(_state.last_check_errors)} ошибок.",
            )

    except (ValueError, TypeError, ConnectionError, OSError, AttributeError, KeyError) as e:
        logger.error("scheduler.critical_error", error=str(e))
        await _event_bus.publish(Events.CHECK_ERROR, {"error": str(e)})
        _metrics.counter("check_errors_total").inc()

        # Alert for repeated errors
        _alerting.record_error("scheduler_error", str(e))
        _alerting.check_rules({"error_type": "scheduler_error", "error_count": _alerting.get_error_count("scheduler_error")})
        _state.last_check_errors.append(str(e))
        try:
            await application.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=f"{E.SIREN} **Критическая ошибка**\n\n{str(e)[:200]}"
            )
        except (TelegramError, ValueError, TypeError):
            pass
    finally:
        _state.is_checking = False
        _metrics.gauge("scheduler.is_checking").set(0)
        await monitor.cleanup()


async def check_monitor_health(application: Application) -> None:
    """Check if monitor is running and alert if not."""
    minutes_since = (datetime.now() - _state.last_check_time).total_seconds() / 60

    if minutes_since > 40:
        try:
            await application.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=f"{E.SIREN} **Мониторинг не работает**\n\nПоследняя проверка: {int(minutes_since)} минут назад.\nПроверьте /health"
            )
            logger.error("scheduler.health_alert", minutes_since=int(minutes_since))
        except (TelegramError, ValueError, TypeError):
            pass

        # Alerting
        _alerting.record_error("monitor_down", "monitor not running")
        _alerting.check_rules({"error_type": "monitor_down", "minutes_since_check": minutes_since})


async def cleanup_blacklist_expired() -> None:
    """Clean up expired blacklist entries."""
    try:
        bs = BlacklistService(DB_PATH)
        removed = await bs.cleanup_expired()
        if removed > 0:
            logger.info("scheduler.blacklist_cleanup", removed=removed)
    except (ValueError, TypeError, ConnectionError, OSError, AttributeError) as e:
        logger.error("scheduler.blacklist_cleanup_error", error=str(e))
