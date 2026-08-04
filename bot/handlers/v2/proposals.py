"""Proposal flow: generate → review → edit → send (§3.5, §6.4, §7).

Basic tier gets a deterministic template with manual editing; Pro/Business
get AI generation grounded exclusively in portfolio facts. Sending marks the
proposal, creates/updates the CRM client and schedules the follow-up
reminder (§3.7–3.8). Delivery to the exchange itself stays manual in MVP —
the bot never posts anywhere on the user's behalf.
"""
from typing import Any, List, Optional, Tuple, cast

from sqlalchemy import desc, select
from sqlalchemy.engine import CursorResult
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import BaseHandler, CallbackQueryHandler, ContextTypes

from bot.handlers.v2.cards import proposal_card, proposal_keyboard
from bot.handlers.v2.common import deny_no_access, esc, get_or_create_user, pending
from emoji_config import E, P
from core import crm, tariffs
from core.db import get_session_factory
from core.generation import (
    GenerationResult,
    GuardrailError,
    generate_portfolio_intro,
    generate_proposal,
    render_template_proposal,
    select_relevant_cases,
    validate_proposal,
)
from core.llm import LLMError, get_shared_llm_client
from core.models import (
    NotificationDelivery,
    PortfolioItem,
    Project,
    ProjectAnalysis,
    Proposal,
    ProposalMode,
    ProposalStatus,
    User,
    utcnow,
)
from services.logger_config import get_logger

logger = get_logger(__name__)


async def _load_portfolio(session: AsyncSession, user_id: int) -> List[PortfolioItem]:
    result = await session.execute(
        select(PortfolioItem).where(PortfolioItem.user_id == user_id)
    )
    return list(result.scalars().all())


async def _project_visible_to_user(
    session: AsyncSession, project_id: int, user_id: int
) -> bool:
    """Authorize that ``project_id`` is visible to ``user_id`` (§8 data isolation).

    A project is a global row inserted by the collector, so ``session.get`` alone
    is an IDOR: a forged ``v2p:gen:<foreign_id>`` would disclose another
    tenant's title/description in the generated proposal card. Visibility is
    established only when the project was actually delivered to the user
    (``NotificationDelivery``) or analyzed for them (``ProjectAnalysis``) — both
    are created by the worker strictly from the user's own connections.
    """
    delivered = (
        await session.execute(
            select(NotificationDelivery.id)
            .where(
                NotificationDelivery.project_id == project_id,
                NotificationDelivery.user_id == user_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if delivered is not None:
        return True
    analyzed = (
        await session.execute(
            select(ProjectAnalysis.id)
            .where(
                ProjectAnalysis.project_id == project_id,
                ProjectAnalysis.user_id == user_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return analyzed is not None


#: Per-user cooldown between AI-generating actions (S-11). Prevents a single
#: user from burning OpenRouter tokens by spam-tapping «Отклики»/«Ещё вариант».
AI_ACTION_COOLDOWN_SECONDS = 60.0
#: Maximum AI-generation calls per user per hour (rate-limit budget, CR-5).
AI_GENERATION_LIMIT_PER_HOUR = 10


def _ai_cooldown_active(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the user is still within the AI-action cooldown window."""
    data = context.user_data or {}
    last = data.get("v2_ai_action_at")
    if last is None:
        return False
    elapsed = (utcnow() - last).total_seconds()
    if elapsed < AI_ACTION_COOLDOWN_SECONDS:
        return True
    return False


def _mark_ai_action(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stamp the AI-action cooldown and increment the hourly counter."""
    data = context.user_data or {}
    data["v2_ai_action_at"] = utcnow()
    hour_key = "v2_ai_gen_hour"
    hour_stamp = data.get("v2_ai_gen_hour_stamp", 0)
    now_ts = int(utcnow().timestamp())
    if now_ts - hour_stamp >= 3600:
        data[hour_key] = 0
        data["v2_ai_gen_hour_stamp"] = now_ts
    data[hour_key] = data.get(hour_key, 0) + 1


def _ai_hourly_limit_exceeded(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the user has exceeded the hourly AI-generation budget."""
    data = context.user_data or {}
    hour_stamp = data.get("v2_ai_gen_hour_stamp", 0)
    now_ts = int(utcnow().timestamp())
    if now_ts - hour_stamp >= 3600:
        return False
    return data.get("v2_ai_gen_hour", 0) >= AI_GENERATION_LIMIT_PER_HOUR


async def _latest_analysis(
    session: AsyncSession, project_id: int, user_id: int
) -> Optional[ProjectAnalysis]:
    result = await session.execute(
        select(ProjectAnalysis)
        .where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.user_id == user_id,
        )
        .order_by(desc(ProjectAnalysis.computed_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _build_proposal_text(
    project: Project,
    user: User,
    portfolio: List[PortfolioItem],
    analysis: Optional[ProjectAnalysis],
    ai_enabled: bool,
) -> Tuple[str, ProposalMode, List[str]]:
    """Produce proposal text per tariff (§7): template for Basic, AI for Pro+."""
    project_text = f"{project.title}\n\n{project.description_raw}"
    required = list(analysis.extracted_skills) if analysis is not None else []
    llm = get_shared_llm_client() if ai_enabled else None
    if ai_enabled and llm is not None:
        from config import get_config

        result: GenerationResult = await generate_proposal(
            project_text,
            portfolio,
            llm,
            model=get_config().GENERATION_MODEL,
            required_skills=required,
        )
        return result.text, ProposalMode.AI, result.violations
    text = render_template_proposal(
        project.title, portfolio, budget_line=project.budget_raw
    )
    violations = validate_proposal(text, portfolio)
    return text, ProposalMode.TEMPLATE, violations


async def proposal_generate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle «✍️ Отклик» under a project card."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    project_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        tier = tariffs.effective_tier(user)
        if tier is None:
            await deny_no_access(update)
            return
        if not await _project_visible_to_user(session, project_id, user.id):
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return
        project = await session.get(Project, project_id)
        if project is None:
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return
        # T-4: a quick double-tap on «Отклики» used to create two drafts for the
        # same (project, user). Reuse an existing DRAFT without a new LLM call.
        existing = (
            await session.execute(
                select(Proposal)
                .where(
                    Proposal.project_id == project.id,
                    Proposal.user_id == user.id,
                    Proposal.status == ProposalStatus.DRAFT,
                )
                .order_by(desc(Proposal.id))
                .limit(1)
            )
        ).scalar_one_or_none()
        ai_enabled = tariffs.can_use_ai_generation(tier)
        if existing is not None:
            # A draft already exists — show it without regenerating (saves LLM
            # tokens on a double-tap). The user can «Редактировать»/«Ещё вариант».
            await query.answer()
            await query.message.reply_text(  # type: ignore[union-attr]
                proposal_card(existing, project),
                parse_mode="HTML",
                reply_markup=proposal_keyboard(existing.id, ai_enabled),
            )
            return
        # S-11: per-user cooldown on AI-generating actions (token-abuse guard).
        if _ai_cooldown_active(context):
            await query.answer(
                f"{P.HOURGLASS} Подождите немного — предыдущий отклик ещё готовится.",
                show_alert=True,
            )
            return
        if _ai_hourly_limit_exceeded(context):
            await query.answer(
                f"{P.HOURGLASS} Лимит генераций в час исчерпан — попробуйте позже.",
                show_alert=True,
            )
            return
        portfolio = await _load_portfolio(session, user.id)
        analysis = await _latest_analysis(session, project.id, user.id)
        await query.answer(f"{P.WRITING} Готовлю отклик…")
        _mark_ai_action(context)
        try:
            text, mode, violations = await _build_proposal_text(
                project, user, portfolio, analysis, ai_enabled
            )
        except GuardrailError as exc:
            await query.message.reply_text(str(exc))  # type: ignore[union-attr]
            return
        except LLMError as exc:
            logger.error("v2.generation_failed", error=str(exc))
            await query.message.reply_text(  # type: ignore[union-attr]
                f"{P.WARNING} Модель сейчас недоступна — попробуйте ещё раз через минуту."
            )
            return
        proposal = Proposal(
            project_id=project.id,
            user_id=user.id,
            generated_text=text,
            mode=mode,
            violations=violations,
        )
        session.add(proposal)
        await session.commit()
        await query.message.reply_text(  # type: ignore[union-attr]
            proposal_card(proposal, project),
            parse_mode="HTML",
            reply_markup=proposal_keyboard(proposal.id, ai_enabled),
        )


async def proposal_regenerate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle «🔁 Ещё вариант» (Pro/Business)."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    proposal_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        tier = tariffs.effective_tier(user)
        proposal = await session.get(Proposal, proposal_id)
        if proposal is None or proposal.user_id != user.id:
            await query.answer(f"{P.CROSS} Черновик не найден.", show_alert=True)
            return
        if not tariffs.can_use_ai_generation(tier):
            await query.answer(
                f"{P.LOCK} Перегенерация доступна на Радар PRO.", show_alert=True
            )
            return
        # S-11: per-user cooldown on AI-generating actions (token-abuse guard).
        if _ai_cooldown_active(context):
            await query.answer(
                f"{P.HOURGLASS} Подождите немного — предыдущий вариант ещё готовится.",
                show_alert=True,
            )
            return
        project = await session.get(Project, proposal.project_id)
        if project is None:
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return
        portfolio = await _load_portfolio(session, user.id)
        analysis = await _latest_analysis(session, project.id, user.id)
        await query.answer(f"{P.RELOAD} Генерирую новый вариант…")
        _mark_ai_action(context)
        try:
            text, mode, violations = await _build_proposal_text(
                project, user, portfolio, analysis, ai_enabled=True
            )
        except (GuardrailError, LLMError) as exc:
            await query.message.reply_text(str(exc))  # type: ignore[union-attr]
            return
        proposal.generated_text = text
        proposal.mode = mode
        proposal.violations = violations
        proposal.status = ProposalStatus.DRAFT
        await session.commit()
        await query.edit_message_text(
            proposal_card(proposal, project),
            parse_mode="HTML",
            reply_markup=proposal_keyboard(proposal.id, True),
        )


async def proposal_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle «✏️ Редактировать» — ask for replacement text.

    Ownership is verified HERE (not only on apply): callback data carries a
    raw id that a user could forge.
    """
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    proposal_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        proposal = await session.get(Proposal, proposal_id)
        if proposal is None or proposal.user_id != user.id:
            await query.answer(f"{P.CROSS} Черновик не найден.", show_alert=True)
            return
        await session.commit()
    pending(context)["v2_edit_proposal"] = proposal_id
    await query.answer()
    await query.message.reply_text(  # type: ignore[union-attr]
        "Пришлите новый текст отклика одним сообщением."
    )


async def apply_proposal_edit(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """Apply edited text sent by the user (router flow)."""
    if update.effective_user is None or update.message is None:
        return
    proposal_id = int(pending(context).pop("v2_edit_proposal", 0))
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        proposal = await session.get(Proposal, proposal_id)
        if proposal is None or proposal.user_id != user.id:
            await update.message.reply_text(f"{P.CROSS} Черновик не найден.")
            return
        portfolio = await _load_portfolio(session, user.id)
        proposal.generated_text = text.strip()
        proposal.status = ProposalStatus.EDITED
        proposal.violations = validate_proposal(proposal.generated_text, portfolio)
        project = await session.get(Project, proposal.project_id)
        tier = tariffs.effective_tier(user)
        await session.commit()
        await update.message.reply_text(
            proposal_card(proposal, project),
            parse_mode="HTML",
            reply_markup=proposal_keyboard(
                proposal.id, tariffs.can_use_ai_generation(tier)
            ),
        )


async def proposal_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «📤 Отправлено»: mark sent + CRM card + reminder (§3.7–3.8)."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    proposal_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        tier = tariffs.effective_tier(user)
        if tier is None:
            await deny_no_access(update)
            return
        proposal = await session.get(Proposal, proposal_id)
        if proposal is None or proposal.user_id != user.id:
            await query.answer(f"{P.CROSS} Черновик не найден.", show_alert=True)
            return
        # Atomic claim: only ONE of two racing taps flips DRAFT/EDITED→SENT
        # and runs the CRM side effects (idempotent double-tap).
        claim = await session.execute(
            sa_update(Proposal)
            .where(
                Proposal.id == proposal_id,
                Proposal.user_id == user.id,
                Proposal.status != ProposalStatus.SENT,
            )
            .values(status=ProposalStatus.SENT, sent_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        # CursorResult.rowcount is the affected-row count for this UPDATE;
        # typed as Result by SQLAlchemy stubs, hence the cast.
        if cast("CursorResult[Any]", claim).rowcount == 0:
            await session.rollback()
            await query.answer(f"{P.CHECK} Уже отмечен отправленным.")
            return
        await session.refresh(proposal)
        project = await session.get(Project, proposal.project_id)
        if project is None:
            await session.rollback()
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return

        crm_note = ""
        active = await crm.count_active_clients(session, user.id)
        if tariffs.can_add_active_client(tier, active):
            client = await crm.upsert_client_for_proposal(
                session,
                user,
                project,
                proposal,
                with_reminder=tariffs.can_use_reminders(tier),
            )
            crm_note = f"\nКлиент в CRM: {esc(client.name)} (/clients)"
        else:
            crm_note = (
                f"\n{E.WARNING} Лимит активных клиентов CRM на тарифе исчерпан — "
                "карточка не создана."
            )
        await session.commit()
    await query.answer(f"{P.CHECK} Отклик зафиксирован.")
    await query.message.reply_text(  # type: ignore[union-attr]
        f"{E.CHECK} Отклик отмечен отправленным.{crm_note}", parse_mode="HTML"
    )


async def proposal_hide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «🙈 Скрыть» under a project card.

    Authorization (BL-7): the callback carries a project id; we require an
    authenticated user, an active subscription, and that the project is visible
    to that user — otherwise an expired/non-subscriber could forge the callback
    to delete arbitrary bot messages carrying a ``v2p:hide:<id>`` payload.
    """
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    try:
        project_id = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        await query.answer()
        return
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        if tariffs.effective_tier(user) is None:
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return
        if not await _project_visible_to_user(session, project_id, user.id):
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return
        await session.commit()
    await query.answer(f"{P.HIDE} Скрыто.")
    delete = getattr(query.message, "delete", None)
    if delete is not None:
        await delete()


async def proposal_cases(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «🧩 Кейсы под заказ» — portfolio adaptation (§3.6, Pro+)."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    project_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        tier = tariffs.effective_tier(user)
        limits = tariffs.get_limits(tier)
        if limits is None or not limits.portfolio_adaptation:
            await query.answer(
                f"{P.LOCK} Адаптация портфолио доступна на Радар PRO.", show_alert=True
            )
            return
        if not await _project_visible_to_user(session, project_id, user.id):
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return
        project = await session.get(Project, project_id)
        if project is None:
            await query.answer(f"{P.CROSS} Заказ не найден.", show_alert=True)
            return
        portfolio = await _load_portfolio(session, user.id)
        if not portfolio:
            await query.answer(
                f"{P.EMPTY} Портфолио пусто — добавьте кейсы: /portfolio", show_alert=True
            )
            return
        analysis = await _latest_analysis(session, project.id, user.id)
        required = list(analysis.extracted_skills) if analysis is not None else []
        project_text = f"{project.title}\n\n{project.description_raw}"
        cases = select_relevant_cases(portfolio, required, project_text)
        intro = ""
        llm = get_shared_llm_client()
        if llm is not None:
            # S-11: per-user cooldown when an LLM intro will be generated.
            if _ai_cooldown_active(context):
                await query.answer(
                    f"{P.HOURGLASS} Подождите немного — предыдущая адаптация ещё готовится.",
                    show_alert=True,
                )
                return
            _mark_ai_action(context)
            try:
                from config import get_config

                intro = await generate_portfolio_intro(
                    portfolio,
                    project_text,
                    llm,
                    model=get_config().GENERATION_MODEL,
                    required_skills=required,
                )
            except (GuardrailError, LLMError) as exc:
                logger.warning("v2.intro_failed", error=str(exc))
        await query.answer()
        lines = ["\U0001f9e9 <b>Кейсы под этот заказ</b>"]
        if intro:
            lines.append(f"<i>{esc(intro)}</i>")
        for case in cases:
            lines.append(f"• <b>{esc(case.title)}</b> — {esc(case.description[:150])}")
        await query.message.reply_text(  # type: ignore[union-attr]
            "\n".join(lines), parse_mode="HTML"
        )


def get_proposal_handlers() -> List[BaseHandler]:
    """Build proposal-flow callback handlers."""
    return [
        CallbackQueryHandler(proposal_generate, pattern=r"^v2p:gen:\d+$"),
        CallbackQueryHandler(proposal_regenerate, pattern=r"^v2p:regen:\d+$"),
        CallbackQueryHandler(proposal_edit_start, pattern=r"^v2p:edit:\d+$"),
        CallbackQueryHandler(proposal_send, pattern=r"^v2p:send:\d+$"),
        CallbackQueryHandler(proposal_hide, pattern=r"^v2p:hide:\d+$"),
        CallbackQueryHandler(proposal_cases, pattern=r"^v2p:cases:\d+$"),
    ]
