"""V2 worker: periodic collect→analyze→score→notify pipeline (§4.1, §6.2).

Transaction design (audit fixes):
    * Network I/O (scraping, LLM, Telegram) is NEVER performed inside an open
      DB transaction. Phases: fetch → short collect tx → per-(project, user)
      short analyze tx → notify strictly AFTER commit.
    * Extraction runs ONCE per listing (§3.2) and is reused for every
      matching user — scoring is the only per-user part.
    * Idempotency is DB-enforced: unique ``(project_id, user_id)`` on
      analyses makes a restarted/concurrent tick converge instead of
      duplicating notifications.
    * Reminders are at-most-once (§3.8): status is committed BEFORE the
      notification is sent, so a crash never re-pings the user.

Scheduling notes (AGENTS.md §12.7): the V2 tick reuses the SAME
``MONITOR_INTERVAL_MINUTES`` cadence as the legacy monitor — polling
frequency is never increased without explicit approval. "Priority scanning"
for Business (§7) affects notification ordering only, not scrape frequency.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application

from core import crm, tariffs
from core.db import get_session_factory
from core.generation import ExtractionResult, extract_listing, fallback_extraction
from core.llm import OpenRouterClient, get_shared_llm_client
from core.models import (
    Client,
    ConnectionStatus,
    ExchangeConnection,
    Platform,
    PortfolioItem,
    Project,
    ProjectAnalysis,
    Reminder,
    ReminderStatus,
    SubscriptionTier,
    User,
    utcnow,
)
from core.scoring import ScoreResult, estimate_hours, score_project
from emoji_config import E
from monitoring.adapters.base import RawListing, SourceAdapter
from monitoring.collector import Collector
from services.logger_config import get_logger

logger = get_logger(__name__)

#: Notification callable; must return ``False`` on delivery failure.
NotifyFn = Callable[..., Awaitable[Optional[bool]]]

#: Tolerate scheduler lateness up to this many seconds instead of silently
#: dropping a tick (APScheduler default misfire_grace_time=1s is too strict
#: for long Playwright/LLM ticks). This does NOT increase polling frequency.
JOB_MISFIRE_GRACE_SECONDS = 300


@dataclass
class TickStats:
    """Result of one radar tick (for logs/metrics/tests)."""

    listings_fetched: int = 0
    new_projects: int = 0
    analyses: int = 0
    notifications: int = 0
    notify_failures: int = 0
    skipped_quota: int = 0
    errors: List[str] = field(default_factory=list)


async def default_notify(
    application: Application,
    chat_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Send a notification through the bot (HTML parse mode).

    Returns:
        ``True`` on success, ``False`` on delivery failure (logged) — the
        caller must not count a failed delivery as a sent notification.
    """
    try:
        await application.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except (TelegramError, ValueError, TypeError) as exc:
        logger.error("v2.notify_failed", chat_id=chat_id, error=str(exc))
        return False


async def _load_active_connections(
    session: AsyncSession,
) -> Sequence[ExchangeConnection]:
    result = await session.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.status == ConnectionStatus.ACTIVE
        )
    )
    return result.scalars().all()


def build_adapters(
    connections: Sequence[ExchangeConnection],
) -> List[SourceAdapter]:
    """Build the adapter set required by the given connections."""
    adapters: List[SourceAdapter] = []
    platforms = {c.platform for c in connections}
    if Platform.KWORK in platforms:
        from monitoring.adapters.kwork import KworkAdapter

        adapters.append(KworkAdapter())
    if Platform.FL_RU in platforms:
        from monitoring.adapters.fl_ru import FLRuAdapter

        adapters.append(FLRuAdapter())
    channels = sorted(
        {
            str(c.settings.get("channel"))
            for c in connections
            if c.platform is Platform.TG_CHANNEL and c.settings.get("channel")
        }
    )
    if channels:
        from monitoring.adapters.telegram_channels import TelegramChannelsAdapter

        adapters.append(TelegramChannelsAdapter(channels))
    return adapters


def _normalize_channel(channel: str) -> str:
    username = (channel or "").strip().split("/")[-1]
    return username if username.startswith("@") else f"@{username}"


def connection_matches_project(
    connection: ExchangeConnection, project: Project
) -> bool:
    """Does this user connection subscribe to this project's source?"""
    if connection.platform is not project.source:
        return False
    if connection.platform is Platform.TG_CHANNEL:
        wanted = _normalize_channel(str(connection.settings.get("channel", "")))
        actual = _normalize_channel(str(project.raw_payload.get("channel", "")))
        return bool(wanted) and wanted == actual
    return True


async def _analyses_used_this_month(
    session: AsyncSession, user_id: int, now: Optional[datetime] = None
) -> int:
    moment = now or utcnow()
    month_start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.count(ProjectAnalysis.id)).where(
            ProjectAnalysis.user_id == user_id,
            ProjectAnalysis.computed_at >= month_start,
        )
    )
    return int(result.scalar_one())


async def _analysis_exists(
    session: AsyncSession, project_id: int, user_id: int
) -> bool:
    result = await session.execute(
        select(ProjectAnalysis.id).where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def extract_for_project(
    project: Project,
    llm: Optional[OpenRouterClient],
    extraction_model: str,
) -> ExtractionResult:
    """Run extraction ONCE for a listing (§3.2) — user-independent.

    Uses the cheap model when an LLM client is configured, otherwise the
    deterministic parser-field fallback (MVP no-LLM mode).
    """
    if llm is None:
        return fallback_extraction(project)
    return await extract_listing(
        f"{project.title}\n\n{project.description_raw}", llm, extraction_model
    )


def build_analysis(
    project: Project,
    user: User,
    extraction: ExtractionResult,
    portfolio: Sequence[PortfolioItem],
) -> ProjectAnalysis:
    """Build the per-user analysis row from a shared extraction (§3.3–3.4)."""
    analysis = ProjectAnalysis(
        project_id=project.id,
        user_id=user.id,
        extracted_budget=(
            extraction.budget_max or extraction.budget_min or project.budget_max
        ),
        extracted_deadline_days=extraction.deadline_days,
        extracted_skills=extraction.required_skills,
        client_red_flags=extraction.client_red_flags,
        summary=extraction.summary or None,
        needs_manual_review=extraction.needs_manual_review,
        estimated_hours=estimate_hours(project.category, extraction.deadline_days),
    )
    score: ScoreResult = score_project(project, user, portfolio, analysis=analysis)
    analysis.needs_manual_review = (
        analysis.needs_manual_review or score.needs_manual_review
    )
    analysis.win_probability = score.win_probability
    if score.profitability is not None:
        analysis.profitability_index = score.profitability.profitability_index
        analysis.effective_hourly_rate = score.profitability.effective_hourly_rate
        analysis.net_payout = score.profitability.net_payout
        analysis.estimated_hours = score.profitability.estimated_hours
    return analysis


async def analyze_project_for_user(
    session: AsyncSession,
    project: Project,
    user: User,
    llm: Optional[OpenRouterClient],
    extraction_model: str,
    extraction: Optional[ExtractionResult] = None,
) -> ProjectAnalysis:
    """Extraction (reused when provided) + scoring; persists the analysis.

    Kept as a public seam for handlers/tests; the tick passes a precomputed
    ``extraction`` so the LLM is called once per listing (§3.2).
    """
    if extraction is None:
        extraction = await extract_for_project(project, llm, extraction_model)
    portfolio = (
        (
            await session.execute(
                select(PortfolioItem).where(PortfolioItem.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    analysis = build_analysis(project, user, extraction, portfolio)
    session.add(analysis)
    await session.flush()
    return analysis


def _connection_priority(
    connection: ExchangeConnection, users_by_id: Dict[int, User]
) -> int:
    """Business first (§7): priority is notification ORDER, not scrape rate."""
    user = users_by_id.get(connection.user_id)
    if user is None:
        return 1
    tier = tariffs.effective_tier(user)
    limits = tariffs.get_limits(tier)
    return 0 if limits is not None and limits.priority_scan else 1


async def _fetch_listings(
    adapters: Sequence[SourceAdapter], stats: TickStats
) -> List[RawListing]:
    """Fetch from every adapter, isolating per-source failures (§3.1)."""
    listings: List[RawListing] = []
    for adapter in adapters:
        try:
            listings.extend(await adapter.fetch())
        except Exception as exc:  # noqa: BLE001 - isolate any source failure
            stats.errors.append(f"{adapter.platform.value}: {exc}")
            logger.error(
                "v2.adapter_failed",
                platform=adapter.platform.value,
                error=str(exc),
            )
    return listings


async def _close_adapters(adapters: Sequence[SourceAdapter]) -> None:
    """Release adapter resources (httpx pools, TG sessions) after a tick."""
    for adapter in adapters:
        try:
            await adapter.close()
        except Exception as exc:  # noqa: BLE001 - closing must never raise
            logger.warning(
                "v2.adapter_close_failed",
                platform=adapter.platform.value,
                error=str(exc),
            )


async def _persist_analysis(
    factory: async_sessionmaker,
    project: Project,
    user: User,
    extraction: ExtractionResult,
) -> Optional[ProjectAnalysis]:
    """Short transaction: build + insert one analysis, commit.

    Returns ``None`` when a concurrent tick already inserted the pair
    (unique ``project_id+user_id``) — the caller must then skip notification.
    """
    async with factory() as session:
        try:
            analysis = await analyze_project_for_user(
                session, project, user, None, "", extraction=extraction
            )
            await session.commit()
            return analysis
        except IntegrityError:
            await session.rollback()
            logger.info(
                "v2.analysis_concurrent_duplicate",
                project_id=project.id,
                user_id=user.id,
            )
            return None


async def run_radar_tick(
    application: Optional[Application],
    session_factory: Optional[async_sessionmaker] = None,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    llm: Optional[OpenRouterClient] = None,
    notify: Optional[NotifyFn] = None,
    extraction_model: Optional[str] = None,
    auto_llm: bool = True,
) -> TickStats:
    """One full monitoring tick: fetch → collect → analyze → notify.

    All dependencies are injectable for tests; production wiring passes only
    ``application``. ``auto_llm=False`` disables building the default LLM
    client (tests inject ``llm`` explicitly or run the no-LLM fallback path).
    """
    from config import get_config

    cfg = get_config()
    factory = session_factory or get_session_factory()
    notify_fn: NotifyFn = notify or default_notify
    model = extraction_model or cfg.EXTRACTION_MODEL
    stats = TickStats()

    # Phase 0: read connections + users (short read-only session).
    # Known staleness window: user rows are read once per tick — a tariff
    # upgrade committed mid-tick becomes visible on the NEXT tick. Time-based
    # expiry is unaffected (effective_tier re-evaluates the clock per call).
    async with factory() as session:
        connections = list(await _load_active_connections(session))
        if not connections:
            return stats
        users_by_id: Dict[int, User] = {}
        for connection in connections:
            if connection.user_id not in users_by_id:
                user = await session.get(User, connection.user_id)
                if user is not None:
                    users_by_id[connection.user_id] = user

    # Phase 1: fetch listings — network only, no open transaction.
    adapters_owned = adapters is None
    active_adapters = (
        list(adapters) if adapters is not None else build_adapters(connections)
    )
    try:
        listings = await _fetch_listings(active_adapters, stats)
    finally:
        if adapters_owned:
            await _close_adapters(active_adapters)
    stats.listings_fetched = len(listings)

    # Phase 2: collect (short transaction, committed immediately).
    async with factory() as session:
        collect_result = await Collector().collect(session, listings)
        await session.commit()
    new_projects = collect_result.new_projects
    stats.new_projects = len(new_projects)
    if not new_projects:
        logger.info("v2.tick_done", **_tick_log_fields(stats))
        return stats

    client = llm if llm is not None else (
        get_shared_llm_client() if auto_llm else None
    )
    ordered_connections = sorted(
        connections, key=lambda c: _connection_priority(c, users_by_id)
    )

    # Phase 3: per (project, user) — extract once per project, short
    # analyze transactions, notify strictly after commit.
    for project in new_projects:
        extraction: Optional[ExtractionResult] = None
        handled_users: Set[int] = set()
        for connection in ordered_connections:
            user = users_by_id.get(connection.user_id)
            if user is None or user.id in handled_users:
                continue
            if not connection_matches_project(connection, project):
                continue
            handled_users.add(user.id)
            tier = tariffs.effective_tier(user)
            if tier is None:
                continue
            async with factory() as session:
                if await _analysis_exists(session, project.id, user.id):
                    continue
                used = await _analyses_used_this_month(session, user.id)
            if not tariffs.can_analyze(tier, used):
                stats.skipped_quota += 1
                continue
            if extraction is None:
                # §3.2: ONE extraction per listing, reused for all users.
                extraction = await extract_for_project(project, client, model)
            analysis = await _persist_analysis(factory, project, user, extraction)
            if analysis is None:
                continue
            stats.analyses += 1
            if application is not None or notify is not None:
                from bot.handlers.v2.cards import (
                    project_card,
                    project_card_keyboard,
                )

                delivered = await notify_fn(
                    application,
                    user.telegram_id,
                    project_card(project, analysis),
                    project_card_keyboard(project.id),
                )
                if delivered is False:
                    stats.notify_failures += 1
                else:
                    stats.notifications += 1

    logger.info("v2.tick_done", **_tick_log_fields(stats))
    return stats


def _tick_log_fields(stats: TickStats) -> Dict[str, int]:
    return {
        "fetched": stats.listings_fetched,
        "new": stats.new_projects,
        "analyses": stats.analyses,
        "notified": stats.notifications,
        "notify_failures": stats.notify_failures,
        "quota_skipped": stats.skipped_quota,
        "errors": len(stats.errors),
    }


async def _claim_due_reminder(
    factory: async_sessionmaker, reminder_id: int
) -> Optional[Tuple[Reminder, Client, User]]:
    """Atomically mark one reminder NOTIFIED and commit (at-most-once, §3.8).

    Returns the loaded rows for notification, or ``None`` when the reminder
    is no longer eligible (already handled, tariff without reminders, or
    orphaned rows — those are completed silently).
    """
    async with factory() as session:
        reminder = (
            await session.execute(
                select(Reminder)
                .where(
                    Reminder.id == reminder_id,
                    Reminder.status == ReminderStatus.PENDING,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if reminder is None:
            return None
        client_row = await session.get(Client, reminder.client_id)
        if client_row is None:
            await crm.complete_reminder(session, reminder)
            await session.commit()
            return None
        user = await session.get(User, client_row.user_id)
        if user is None:
            await crm.complete_reminder(session, reminder)
            await session.commit()
            return None
        tier = tariffs.effective_tier(user)
        if not tariffs.can_use_reminders(tier):
            await crm.complete_reminder(session, reminder)
            await session.commit()
            return None
        await crm.mark_notified(session, reminder)
        await session.commit()
        return reminder, client_row, user


async def run_reminders_tick(
    application: Optional[Application],
    session_factory: Optional[async_sessionmaker] = None,
    notify: Optional[NotifyFn] = None,
) -> int:
    """Deliver due reminders (§3.8): status committed BEFORE sending.

    At-most-once semantics: a crash between commit and send loses at most
    one ping but never re-pings the user (§3.8 forbids repeated escalation).
    """
    factory = session_factory or get_session_factory()
    notify_fn: NotifyFn = notify or default_notify
    delivered = 0
    async with factory() as session:
        due: Sequence[Reminder] = await crm.find_due_reminders(session)
        due_ids = [reminder.id for reminder in due]

    for reminder_id in due_ids:
        claimed = await _claim_due_reminder(factory, reminder_id)
        if claimed is None:
            continue
        reminder, client_row, user = claimed
        from bot.handlers.v2.cards import reminder_card, reminder_keyboard

        result = await notify_fn(
            application,
            user.telegram_id,
            reminder_card(client_row, reminder),
            reminder_keyboard(reminder.id, client_row.id),
        )
        if result is not False:
            delivered += 1
    if delivered:
        logger.info("v2.reminders_delivered", count=delivered)
    return delivered


async def run_weekly_report_tick(
    application: Optional[Application],
    session_factory: Optional[async_sessionmaker] = None,
    notify: Optional[NotifyFn] = None,
) -> int:
    """Send the weekly digest to tiers that include it (§7: Pro/Business).

    A compact, honest summary of the last 7 days: analyses, best win
    probability, proposals sent, active CRM pipeline.
    """
    from datetime import timedelta

    from sqlalchemy import and_

    from core.models import Proposal, ProposalStatus

    factory = session_factory or get_session_factory()
    notify_fn: NotifyFn = notify or default_notify
    week_ago = utcnow() - timedelta(days=7)
    delivered = 0

    async with factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            tier = tariffs.effective_tier(user)
            limits = tariffs.get_limits(tier)
            if limits is None or not limits.weekly_report:
                continue
            analyses = (
                await session.execute(
                    select(
                        func.count(ProjectAnalysis.id),
                        func.max(ProjectAnalysis.win_probability),
                    ).where(
                        ProjectAnalysis.user_id == user.id,
                        ProjectAnalysis.computed_at >= week_ago,
                    )
                )
            ).one()
            proposals_sent = (
                await session.execute(
                    select(func.count(Proposal.id)).where(
                        and_(
                            Proposal.user_id == user.id,
                            Proposal.status == ProposalStatus.SENT,
                            Proposal.sent_at >= week_ago,
                        )
                    )
                )
            ).scalar_one()
            active_clients = await crm.count_active_clients(session, user.id)
            if not analyses[0] and not proposals_sent and not active_clients:
                continue  # nothing to report — no noise (§3.8 spirit)
            best = (
                f"{analyses[1]:.0f}%" if analyses[1] is not None else "—"
            )
            text = (
                f"{E.CHART} <b>Неделя в FreelanceRadar</b>\n"
                f"Проанализировано заказов: <b>{analyses[0]}</b>\n"
                f"Лучшая вероятность: <b>{best}</b>\n"
                f"Откликов отправлено: <b>{proposals_sent}</b>\n"
                f"Активных клиентов в CRM: <b>{active_clients}</b>\n\n"
                "Продуктивной недели! /radar"
            )
            result = await notify_fn(application, user.telegram_id, text, None)
            if result is not False:
                delivered += 1
    if delivered:
        logger.info("v2.weekly_reports_sent", count=delivered)
    return delivered


#: Warn this many days before the subscription/trial ends (§7 monetization).
EXPIRY_WARN_DAYS = 2


def _expiry_message(user: User, days: Optional[int], expired: bool) -> str:
    """Build the expiry nudge text (honest, one CTA, no dark patterns)."""
    price = tariffs.PRIMARY_PRICE_RUB
    if expired:
        return (
            f"{E.LOCK} <b>Доступ приостановлен</b>\n\n"
            "Сканирование заказов и AI-отклики остановлены. "
            "Портфолио, CRM и история откликов сохранены.\n\n"
            f"Вернуть радар — {price} \u20bd/мес: /subscription"
        )
    tail = f"через {days} дн." if days else "сегодня"
    if user.subscription_tier is SubscriptionTier.TRIAL:
        return (
            f"{E.HOURGLASS} <b>Бесплатный период заканчивается {tail}</b>\n\n"
            "Чтобы радар не остановился — подключите Радар PRO "
            f"за {price} \u20bd/мес: /subscription\n\n"
            "<i>Автосписаний нет — платёж только вручную.</i>"
        )
    return (
        f"{E.HOURGLASS} <b>Подписка заканчивается {tail}</b>\n\n"
        f"Продлить за {price} \u20bd/мес: /subscription"
    )


async def run_expiry_reminders_tick(
    application: Optional[Application],
    session_factory: Optional[async_sessionmaker] = None,
    notify: Optional[NotifyFn] = None,
) -> int:
    """Warn users whose access ends soon, and once after it ended.

    Idempotent per period: ``expiry_notified_at`` is stamped and committed
    BEFORE sending (at-most-once, same discipline as reminders §3.8), so a
    crash never turns into a repeated nag. Users without an expiry date
    (manual grants) are skipped.
    """
    factory = session_factory or get_session_factory()
    notify_fn: NotifyFn = notify or default_notify
    now = utcnow()
    delivered = 0

    async with factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        targets: List[Tuple[int, str]] = []
        for user in users:
            expires = user.subscription_expires_at
            if expires is None:
                continue
            days = tariffs.days_left(user, now)
            expired = expires <= now
            if not expired and (days is None or days > EXPIRY_WARN_DAYS):
                continue
            # One nudge per period: skip if already warned after the last
            # renewal (the stamp is reset on every successful payment).
            if user.expiry_notified_at is not None:
                continue
            user.expiry_notified_at = now
            targets.append(
                (user.telegram_id, _expiry_message(user, days, expired))
            )
        if not targets:
            return 0
        await session.commit()

    for chat_id, text in targets:
        if await notify_fn(application, chat_id, text, None) is not False:
            delivered += 1
    if delivered:
        logger.info("v2.expiry_reminders_sent", count=delivered)
    return delivered


def register_v2_jobs(scheduler: object, application: Application) -> None:
    """Register V2 periodic jobs on the existing APScheduler instance.

    Cadence intentionally mirrors the legacy monitor (§12.7). A generous
    ``misfire_grace_time`` prevents silently dropped ticks when a previous
    run (Playwright + LLM) finishes slightly late; ``coalesce`` collapses a
    backlog into a single run instead of a burst.
    """
    from config import get_config

    interval = get_config().MONITOR_INTERVAL_MINUTES
    scheduler.add_job(  # type: ignore[attr-defined]
        run_radar_tick,
        "interval",
        minutes=interval,
        args=[application],
        id="v2_radar_tick",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=JOB_MISFIRE_GRACE_SECONDS,
    )
    scheduler.add_job(  # type: ignore[attr-defined]
        run_reminders_tick,
        "interval",
        minutes=10,
        args=[application],
        id="v2_reminders_tick",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=JOB_MISFIRE_GRACE_SECONDS,
    )
    scheduler.add_job(  # type: ignore[attr-defined]
        run_expiry_reminders_tick,
        "cron",
        hour=9,  # 12:00 МСК — никогда ночью
        minute=30,
        args=[application],
        id="v2_expiry_reminders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(  # type: ignore[attr-defined]
        run_weekly_report_tick,
        "cron",
        day_of_week="mon",
        hour=6,  # 09:00 МСК
        minute=0,
        args=[application],
        id="v2_weekly_report",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    logger.info("v2.jobs_registered", interval_minutes=interval)
