"""Proposal flow: generate → review → edit → send (§3.5, §6.4, §7).

Basic tier gets a deterministic template with manual editing; Pro/Business
get AI generation grounded exclusively in portfolio facts. Sending marks the
proposal, creates/updates the CRM client and schedules the follow-up
reminder (§3.7–3.8). Delivery to the exchange itself stays manual in MVP —
the bot never posts anywhere on the user's behalf.
"""
from typing import List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import BaseHandler, CallbackQueryHandler, ContextTypes

from bot.handlers.v2.cards import proposal_card, proposal_keyboard
from bot.handlers.v2.common import NO_ACCESS_TEXT, esc, get_or_create_user, pending
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
from core.llm import LLMError, get_default_llm_client
from core.models import (
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
    llm = get_default_llm_client() if ai_enabled else None
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
            await query.answer(NO_ACCESS_TEXT, show_alert=True)
            return
        project = await session.get(Project, project_id)
        if project is None:
            await query.answer("Заказ не найден.", show_alert=True)
            return
        portfolio = await _load_portfolio(session, user.id)
        analysis = await _latest_analysis(session, project.id, user.id)
        ai_enabled = tariffs.can_use_ai_generation(tier)
        await query.answer("Готовлю отклик…")
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
                "Модель сейчас недоступна — попробуйте ещё раз через минуту."
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
            await query.answer("Черновик не найден.", show_alert=True)
            return
        if not tariffs.can_use_ai_generation(tier):
            await query.answer(
                "Перегенерация доступна на Pro/Business.", show_alert=True
            )
            return
        project = await session.get(Project, proposal.project_id)
        if project is None:
            await query.answer("Заказ не найден.", show_alert=True)
            return
        portfolio = await _load_portfolio(session, user.id)
        analysis = await _latest_analysis(session, project.id, user.id)
        await query.answer("Генерирую новый вариант…")
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
    """Handle «✏️ Редактировать» — ask for replacement text."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    proposal_id = int(query.data.split(":")[2])
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
            await update.message.reply_text("Черновик не найден.")
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
            await query.answer(NO_ACCESS_TEXT, show_alert=True)
            return
        proposal = await session.get(Proposal, proposal_id)
        if proposal is None or proposal.user_id != user.id:
            await query.answer("Черновик не найден.", show_alert=True)
            return
        if proposal.status is ProposalStatus.SENT:
            await query.answer("Уже отмечен отправленным.")
            return
        project = await session.get(Project, proposal.project_id)
        if project is None:
            await query.answer("Заказ не найден.", show_alert=True)
            return
        proposal.status = ProposalStatus.SENT
        proposal.sent_at = utcnow()

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
                "\n⚠️ Лимит активных клиентов CRM на тарифе исчерпан — "
                "карточка не создана."
            )
        await session.commit()
    await query.answer("Отклик зафиксирован.")
    await query.message.reply_text(  # type: ignore[union-attr]
        f"✅ Отклик отмечен отправленным.{crm_note}", parse_mode="HTML"
    )


async def proposal_hide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «🙈 Скрыть» under a project card."""
    query = update.callback_query
    if query is None:
        return
    await query.answer("Скрыто.")
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
                "Адаптация портфолио доступна на Pro/Business.", show_alert=True
            )
            return
        project = await session.get(Project, project_id)
        if project is None:
            await query.answer("Заказ не найден.", show_alert=True)
            return
        portfolio = await _load_portfolio(session, user.id)
        if not portfolio:
            await query.answer(
                "Портфолио пусто — добавьте кейсы: /portfolio", show_alert=True
            )
            return
        analysis = await _latest_analysis(session, project.id, user.id)
        required = list(analysis.extracted_skills) if analysis is not None else []
        project_text = f"{project.title}\n\n{project.description_raw}"
        cases = select_relevant_cases(portfolio, required, project_text)
        intro = ""
        llm = get_default_llm_client()
        if llm is not None:
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
