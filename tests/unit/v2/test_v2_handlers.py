"""Bot handler tests: onboarding, sources, portfolio, proposals, CRM, subscription."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import ConversationHandler

import bot.handlers.v2.proposals as proposals_module
from bot.handlers.v2.common import get_or_create_user
from bot.handlers.v2.onboarding import (
    RATE,
    SKILLS,
    TAX,
    onboarding_rate,
    onboarding_skills,
    onboarding_tax,
    radar_entry,
)
from bot.handlers.v2.portfolio import (
    P_DESC,
    P_TAGS,
    portfolio_add_desc,
    portfolio_add_tags,
    portfolio_add_title,
)
from bot.handlers.v2.proposals import (
    apply_proposal_edit,
    proposal_generate,
    proposal_send,
)
from bot.handlers.v2.router import v2_text_router
from bot.handlers.v2.sources import source_add
from bot.handlers.v2.subscription import grant_subscription, subscription_info
from core.models import (
    Client,
    ExchangeConnection,
    Platform,
    PortfolioItem,
    ProjectAnalysis,
    Proposal,
    ProposalMode,
    ProposalStatus,
    Reminder,
    SubscriptionTier,
    User,
    utcnow,
)
from tests.unit.v2.conftest import (
    GOOD_PROPOSAL,
    FakeLLM,
    make_context,
    make_update,
)

OWNER_ID = 123456789


class TestGetOrCreateUser:
    async def test_first_touch_creates_trial(self, session: AsyncSession) -> None:
        """§7: new users get a 7-day trial without a card."""
        from types import SimpleNamespace

        tg_user = SimpleNamespace(id=777, username="newbie")
        user, created = await get_or_create_user(session, tg_user)
        assert created is True
        assert user.subscription_tier is SubscriptionTier.TRIAL
        assert user.subscription_expires_at is not None
        delta = user.subscription_expires_at - utcnow()
        assert timedelta(days=6) < delta <= timedelta(days=7)

        again, created_again = await get_or_create_user(session, tg_user)
        assert created_again is False
        assert again.id == user.id


class TestOnboarding:
    async def test_new_user_flow(self, session_factory) -> None:
        """rate → tax → skills persists the profile."""
        update = make_update(telegram_id=888001, text="/radar")
        context = make_context()
        state = await radar_entry(update, context)
        assert state == RATE

        update = make_update(telegram_id=888001, text="2000")
        assert await onboarding_rate(update, context) == TAX

        update = make_update(telegram_id=888001, text="6")
        assert await onboarding_tax(update, context) == SKILLS

        update = make_update(telegram_id=888001, text="python, боты, парсинг")
        state = await onboarding_skills(update, context)
        assert state == ConversationHandler.END

        async with session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.telegram_id == 888001)
                )
            ).scalar_one()
        assert user.target_hourly_rate == 2000
        assert user.tax_rate == 0.06
        assert user.skills == ["python", "боты", "парсинг"]

    async def test_invalid_rate_reasked(self, session_factory) -> None:
        """Garbage input keeps the state."""
        update = make_update(telegram_id=888002, text="/radar")
        context = make_context()
        await radar_entry(update, context)
        update = make_update(telegram_id=888002, text="дорого")
        assert await onboarding_rate(update, context) == RATE

    async def test_onboarded_user_sees_menu(
        self, session_factory, user
    ) -> None:
        """Existing profile → menu, no questions."""
        update = make_update(text="/radar")
        state = await radar_entry(update, make_context())
        assert state == ConversationHandler.END
        assert update.message.reply_text.await_count == 1


class TestSources:
    async def test_add_kwork_then_duplicate_rejected(
        self, session_factory, user
    ) -> None:
        """Kwork connects once; duplicates are alerts."""
        update = make_update(callback_data="v2s:add:kwork")
        await source_add(update, make_context())
        async with session_factory() as session:
            rows = (
                (await session.execute(select(ExchangeConnection))).scalars().all()
            )
        assert len(rows) == 1 and rows[0].platform is Platform.KWORK

        update = make_update(callback_data="v2s:add:kwork")
        await source_add(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get(
            "show_alert"
        ) is True

    async def test_basic_exchange_limit_enforced(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """§7: Basic = 1 биржа — second exchange denied."""
        user.subscription_tier = SubscriptionTier.BASIC
        session.add(ExchangeConnection(user_id=user.id, platform=Platform.KWORK))
        await session.commit()

        update = make_update(callback_data="v2s:add:fl_ru")
        await source_add(update, make_context())
        async with session_factory() as check:
            rows = (
                (await check.execute(select(ExchangeConnection))).scalars().all()
            )
        assert len(rows) == 1  # fl_ru NOT added

    async def test_tg_channel_flow(self, session_factory, user) -> None:
        """TG add asks for a channel; text router finishes the flow."""
        update = make_update(callback_data="v2s:add:tg")
        context = make_context()
        await source_add(update, context)
        assert context.user_data.get("v2_add_channel") is True

        text_update = make_update(text="t.me/freelance_orders")
        await v2_text_router(text_update, context)
        async with session_factory() as session:
            connection = (
                (await session.execute(select(ExchangeConnection))).scalars().one()
            )
        assert connection.platform is Platform.TG_CHANNEL
        assert connection.settings["channel"] == "@freelance_orders"


class TestPortfolioFlow:
    async def test_add_case_conversation(self, session_factory, user) -> None:
        """title → description → tags saves a case."""
        context = make_context()
        update = make_update(text="Бот для кофейни")
        assert await portfolio_add_title(update, context) == P_DESC
        update = make_update(text="Сделал бота заказов, +30% выручки")
        assert await portfolio_add_desc(update, context) == P_TAGS
        update = make_update(text="python, боты")
        assert await portfolio_add_tags(update, context) == ConversationHandler.END

        async with session_factory() as session:
            item = (
                (await session.execute(select(PortfolioItem))).scalars().one()
            )
        assert item.title == "Бот для кофейни"
        assert item.tags == ["python", "боты"]


class TestProposalFlow:
    @staticmethod
    async def _add_analysis(session: AsyncSession, user, project) -> None:
        """Create a ProjectAnalysis so the user can see the project."""
        analysis = ProjectAnalysis(
            project_id=project.id,
            user_id=user.id,
            extracted_budget=25000,
        )
        session.add(analysis)
        await session.commit()

    async def test_template_mode_for_basic(
        self, session_factory, session: AsyncSession, user, portfolio, project
    ) -> None:
        """§7: Basic → шаблон + ручное редактирование (no LLM call)."""
        user.subscription_tier = SubscriptionTier.BASIC
        await session.commit()
        await self._add_analysis(session, user, project)
        update = make_update(callback_data=f"v2p:gen:{project.id}")
        await proposal_generate(update, make_context())
        async with session_factory() as check:
            proposal = (await check.execute(select(Proposal))).scalars().one()
        assert proposal.mode is ProposalMode.TEMPLATE
        assert "Бот записи для барбершопа" in proposal.generated_text

    async def test_ai_mode_for_trial(
        self,
        session_factory,
        user,
        portfolio,
        project,
        monkeypatch,
    ) -> None:
        """Trial (Pro-level) → AI generation with guardrails."""
        monkeypatch.setattr(
            proposals_module,
            "get_shared_llm_client",
            lambda: FakeLLM([GOOD_PROPOSAL]),
        )
        update = make_update(callback_data=f"v2p:gen:{project.id}")
        await proposal_generate(update, make_context())
        async with session_factory() as check:
            proposal = (await check.execute(select(Proposal))).scalars().one()
        assert proposal.mode is ProposalMode.AI
        assert proposal.violations == []
        assert proposal.generated_text == GOOD_PROPOSAL

    async def test_ai_without_portfolio_refuses(
        self, session_factory, user, project, monkeypatch
    ) -> None:
        """§6.4: no portfolio → guardrail refusal, no Proposal row."""
        monkeypatch.setattr(
            proposals_module,
            "get_shared_llm_client",
            lambda: FakeLLM([GOOD_PROPOSAL]),
        )
        update = make_update(callback_data=f"v2p:gen:{project.id}")
        await proposal_generate(update, make_context())
        reply = update.callback_query.message.reply_text.await_args.args[0]
        assert "Портфолио пусто" in reply
        async with session_factory() as check:
            assert (await check.execute(select(Proposal))).scalars().all() == []

    async def test_edit_then_send_creates_crm_and_reminder(
        self, session_factory, session: AsyncSession, user, portfolio, project
    ) -> None:
        """Edit via router → send → SENT + client card + 48h reminder."""
        proposal = Proposal(
            project_id=project.id,
            user_id=user.id,
            generated_text="Черновик",
            mode=ProposalMode.AI,
        )
        session.add(proposal)
        await session.commit()

        context = make_context()
        context.user_data["v2_edit_proposal"] = proposal.id
        text_update = make_update(text=GOOD_PROPOSAL)
        await apply_proposal_edit(text_update, context, GOOD_PROPOSAL)
        async with session_factory() as check:
            edited = await check.get(Proposal, proposal.id)
            assert edited is not None
            assert edited.status is ProposalStatus.EDITED
            assert edited.violations == []

        update = make_update(callback_data=f"v2p:send:{proposal.id}")
        await proposal_send(update, make_context())
        async with session_factory() as check:
            sent = await check.get(Proposal, proposal.id)
            assert sent is not None and sent.status is ProposalStatus.SENT
            assert sent.sent_at is not None
            client = (await check.execute(select(Client))).scalars().one()
            reminder = (await check.execute(select(Reminder))).scalars().one()
        assert client.platform_client_id == f"kwork:{project.external_id}"
        assert reminder.message  # 48h follow-up scheduled (§3.8)

    async def test_router_dispatches_edit(
        self, session_factory, session: AsyncSession, user, portfolio, project
    ) -> None:
        """Text router picks up the pending edit key."""
        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="Ч"
        )
        session.add(proposal)
        await session.commit()
        context = make_context()
        context.user_data["v2_edit_proposal"] = proposal.id
        update = make_update(text="Новый текст отклика?")
        await v2_text_router(update, context)
        async with session_factory() as check:
            row = await check.get(Proposal, proposal.id)
        assert row is not None and row.generated_text == "Новый текст отклика?"


class TestSubscription:
    async def test_info_renders_usage(self, session_factory, user) -> None:
        """/subscription shows status, quota lines and the single price."""
        update = make_update(text="/subscription")
        await subscription_info(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "Статус" in text and "Анализов за месяц" in text
        assert "300 ₽" in text
        assert "7 дней" in text  # free trial is advertised
        # Old multi-tier prices must be gone from the UI.
        assert "299" not in text and "599" not in text and "999" not in text

    async def test_grant_by_owner(self, session_factory, user) -> None:
        """/grant switches the tier and records a Subscription row."""
        update = make_update(telegram_id=OWNER_ID, text="/grant")
        context = make_context(args=[str(user.telegram_id), "pro", "30"])
        await grant_subscription(update, context)
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(User).where(User.telegram_id == user.telegram_id)
                )
            ).scalar_one()
        assert row.subscription_tier is SubscriptionTier.PRO
        reply = update.message.reply_text.await_args.args[0]
        assert "Радар PRO" in reply

    async def test_grant_denied_for_non_owner(
        self, session_factory, user
    ) -> None:
        """§12: admin commands stay owner-only."""
        update = make_update(telegram_id=999, text="/grant")
        context = make_context(args=[str(user.telegram_id), "pro"])
        await grant_subscription(update, context)
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(User).where(User.telegram_id == user.telegram_id)
                )
            ).scalar_one()
        assert row.subscription_tier is SubscriptionTier.TRIAL
