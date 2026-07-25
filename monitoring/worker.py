"""V2 worker: periodic collect→analyze→score→notify pipeline (§4.1, §6.2).

Scheduling notes (AGENTS.md §12.7): the V2 tick reuses the SAME
``MONITOR_INTERVAL_MINUTES`` cadence as the legacy monitor — polling
frequency is never increased without explicit approval. "Priority scanning"
for Business (§7) affects notification ordering only, not scrape frequency.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application

from core import crm, tariffs
from core.db import get_session_factory
from core.generation import ExtractionResult, extract_listing, fallback_extraction
from core.llm import OpenRouterClient, get_default_llm_client
from core.models import (
    ConnectionStatus,
    ExchangeConnection,
    Platform,
    PortfolioItem,
    Project,
    ProjectAnalysis,
    Reminder,
    User,
    utcnow,
)
from core.scoring import ScoreResult, estimate_hours, score_project
from monitoring.adapters.base import RawListing, SourceAdapter
from monitoring.collector import Collector
from services.logger_config import get_logger

logger = get_logger(__name__)

NotifyFn = Callable[..., Awaitable[None]]


@dataclass
class TickStats:
    """Result of one radar tick (for logs/metrics/tests)."""

    listings_fetched: int = 0
    new_projects: int = 0
    analyses: int = 0
    notifications: int = 0
    skipped_quota: int = 0
    errors: List[str] = field(default_factory=list)


async def default_notify(
    application: Application,
    chat_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Send a notification through the bot (HTML parse mode)."""
    try:
        await application.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except (TelegramError, ValueError, TypeError) as exc:
        logger.error("v2.notify_failed", chat_id=chat_id, error=str(exc))


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


async def analyze_project_for_user(
    session: AsyncSession,
    project: Project,
    user: User,
    llm: Optional[OpenRouterClient],
    extraction_model: str,
) -> ProjectAnalysis:
    """Run extraction (§3.2) + scoring (§3.3–3.4) and persist the analysis."""
    if llm is not None:
        extraction: ExtractionResult = await extract_listing(
            f"{project.title}\n\n{project.description_raw}", llm, extraction_model
        )
    else:
        extraction = fallback_extraction(project)

    portfolio = (
        (
            await session.execute(
                select(PortfolioItem).where(PortfolioItem.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
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
    score: ScoreResult = score_project(
        project, user, portfolio, analysis=analysis
    )
    analysis.needs_manual_review = (
        analysis.needs_manual_review or score.needs_manual_review
    )
    analysis.win_probability = score.win_probability
    if score.profitability is not None:
        analysis.profitability_index = score.profitability.profitability_index
        analysis.effective_hourly_rate = score.profitability.effective_hourly_rate
        analysis.net_payout = score.profitability.net_payout
        analysis.estimated_hours = score.profitability.estimated_hours
    session.add(analysis)
    await session.flush()
    return analysis


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

    async with factory() as session:
        connections = await _load_active_connections(session)
        if not connections:
            return stats

        active_adapters = (
            list(adapters) if adapters is not None else build_adapters(connections)
        )
        listings: List[RawListing] = []
        for adapter in active_adapters:
            try:
                fetched = await adapter.fetch()
                listings.extend(fetched)
            except Exception as exc:  # noqa: BLE001 - isolate any source failure
                stats.errors.append(f"{adapter.platform.value}: {exc}")
                logger.error(
                    "v2.adapter_failed",
                    platform=adapter.platform.value,
                    error=str(exc),
                )
        stats.listings_fetched = len(listings)

        client = llm if llm is not None else (
            get_default_llm_client() if auto_llm else None
        )

        collect_result = await Collector().collect(session, listings)
        stats.new_projects = len(collect_result.new_projects)

        users_by_id: Dict[int, User] = {}
        for connection in connections:
            if connection.user_id not in users_by_id:
                user = await session.get(User, connection.user_id)
                if user is not None:
                    users_by_id[connection.user_id] = user

        # Business tier first (§7: priority scanning = notification priority).
        def _priority(conn: ExchangeConnection) -> int:
            user = users_by_id.get(conn.user_id)
            tier = tariffs.effective_tier(user) if user else None
            return 0 if tier and tariffs.get_limits(tier).priority_scan else 1  # type: ignore[union-attr]

        ordered_connections = sorted(connections, key=_priority)

        for project in collect_result.new_projects:
            notified_users = set()
            for connection in ordered_connections:
                user = users_by_id.get(connection.user_id)
                if user is None or user.id in notified_users:
                    continue
                if not connection_matches_project(connection, project):
                    continue
                tier = tariffs.effective_tier(user)
                if tier is None:
                    continue
                if await _analysis_exists(session, project.id, user.id):
                    continue
                used = await _analyses_used_this_month(session, user.id)
                if not tariffs.can_analyze(tier, used):
                    stats.skipped_quota += 1
                    continue
                analysis = await analyze_project_for_user(
                    session, project, user, client, model
                )
                stats.analyses += 1
                notified_users.add(user.id)
                if application is not None or notify is not None:
                    from bot.handlers.v2.cards import (
                        project_card,
                        project_card_keyboard,
                    )

                    await notify_fn(
                        application,
                        user.telegram_id,
                        project_card(project, analysis),
                        project_card_keyboard(project.id),
                    )
                    stats.notifications += 1
        await session.commit()

    logger.info(
        "v2.tick_done",
        fetched=stats.listings_fetched,
        new=stats.new_projects,
        analyses=stats.analyses,
        notified=stats.notifications,
        quota_skipped=stats.skipped_quota,
        errors=len(stats.errors),
    )
    return stats


async def run_reminders_tick(
    application: Optional[Application],
    session_factory: Optional[async_sessionmaker] = None,
    notify: Optional[NotifyFn] = None,
) -> int:
    """Deliver due reminders (§3.8): one notification, then wait for action."""
    factory = session_factory or get_session_factory()
    notify_fn: NotifyFn = notify or default_notify
    delivered = 0
    async with factory() as session:
        due: Sequence[Reminder] = await crm.find_due_reminders(session)
        for reminder in due:
            client_row = await session.get(
                crm.Client, reminder.client_id  # type: ignore[arg-type]
            )
            if client_row is None:
                await crm.complete_reminder(session, reminder)
                continue
            user = await session.get(User, client_row.user_id)
            if user is None:
                await crm.complete_reminder(session, reminder)
                continue
            tier = tariffs.effective_tier(user)
            if not tariffs.can_use_reminders(tier):
                await crm.complete_reminder(session, reminder)
                continue
            from bot.handlers.v2.cards import reminder_card, reminder_keyboard

            await notify_fn(
                application,
                user.telegram_id,
                reminder_card(client_row, reminder),
                reminder_keyboard(reminder.id, client_row.id),
            )
            await crm.mark_notified(session, reminder)
            delivered += 1
        await session.commit()
    if delivered:
        logger.info("v2.reminders_delivered", count=delivered)
    return delivered


def register_v2_jobs(scheduler: object, application: Application) -> None:
    """Register V2 periodic jobs on the existing APScheduler instance.

    Cadence intentionally mirrors the legacy monitor (§12.7).
    """
    from config import get_config

    interval = get_config().MONITOR_INTERVAL_MINUTES
    scheduler.add_job(  # type: ignore[attr-defined]
        run_radar_tick,
        "interval",
        minutes=interval,
        args=[application],
        id="v2_radar_tick",
    )
    scheduler.add_job(  # type: ignore[attr-defined]
        run_reminders_tick,
        "interval",
        minutes=10,
        args=[application],
        id="v2_reminders_tick",
    )
    logger.info("v2.jobs_registered", interval_minutes=interval)
