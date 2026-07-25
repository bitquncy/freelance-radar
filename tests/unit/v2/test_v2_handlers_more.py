"""Extra handler coverage: proposals edge paths, portfolio, sources, onboarding."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import ConversationHandler

import bot.handlers.v2.proposals as proposals_module
from bot.handlers.v2.onboarding import (
    TAX,
    onboarding_cancel,
    onboarding_tax,
    radar_entry,
)
from bot.handlers.v2.portfolio import (
    P_TITLE,
    portfolio_add_cancel,
    portfolio_add_start,
    portfolio_command,
    portfolio_delete,
)
from bot.handlers.v2.proposals import (
    proposal_cases,
    proposal_generate,
    proposal_hide,
    proposal_regenerate,
    proposal_send,
)
from bot.handlers.v2.sources import source_delete, source_toggle, sources_menu
from bot.handlers.v2.subscription import grant_subscription, subscription_info
from core.llm import LLMError, OpenRouterClient
from core.models import (
    ConnectionStatus,
    ExchangeConnection,
    Platform,
    PortfolioItem,
    Proposal,
    ProposalMode,
    ProposalStatus,
    SubscriptionTier,
    utcnow,
)
from tests.unit.v2.conftest import (
    GOOD_PROPOSAL,
    FakeLLM,
    make_context,
    make_update,
)

OWNER_ID = 123456789


class TestProposalEdges:
    async def test_regenerate_updates_draft(
        self,
        session_factory,
        session: AsyncSession,
        user,
        portfolio,
        project,
        monkeypatch,
    ) -> None:
        """🔁 Ещё вариант replaces text and re-validates."""
        proposal = Proposal(
            project_id=project.id,
            user_id=user.id,
            generated_text="старый",
            mode=ProposalMode.AI,
            status=ProposalStatus.EDITED,
        )
        session.add(proposal)
        await session.commit()
        monkeypatch.setattr(
            proposals_module,
            "get_default_llm_client",
            lambda: FakeLLM([GOOD_PROPOSAL]),
        )
        update = make_update(callback_data=f"v2p:regen:{proposal.id}")
        await proposal_regenerate(update, make_context())
        async with session_factory() as check:
            row = await check.get(Proposal, proposal.id)
        assert row is not None
        assert row.generated_text == GOOD_PROPOSAL
        assert row.status is ProposalStatus.DRAFT
        assert update.callback_query.edit_message_text.await_count == 1

    async def test_regenerate_denied_for_basic(
        self, session_factory, session: AsyncSession, user, project
    ) -> None:
        """Basic cannot regenerate with AI (§7)."""
        user.subscription_tier = SubscriptionTier.BASIC
        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="т"
        )
        session.add(proposal)
        await session.commit()
        update = make_update(callback_data=f"v2p:regen:{proposal.id}")
        await proposal_regenerate(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")

    async def test_generate_llm_error_is_soft(
        self, session_factory, user, portfolio, project, monkeypatch
    ) -> None:
        """LLM outage → friendly message, no crash, no row."""

        class BoomLLM(OpenRouterClient):
            def __init__(self) -> None:
                super().__init__(api_key="x")

            async def chat(self, *args: object, **kwargs: object) -> str:
                raise LLMError("down")

        monkeypatch.setattr(
            proposals_module, "get_default_llm_client", lambda: BoomLLM()
        )
        update = make_update(callback_data=f"v2p:gen:{project.id}")
        await proposal_generate(update, make_context())
        reply = update.callback_query.message.reply_text.await_args.args[0]
        assert "недоступна" in reply
        async with session_factory() as check:
            assert (await check.execute(select(Proposal))).scalars().all() == []

    async def test_expired_user_cannot_generate(
        self, session_factory, session: AsyncSession, user, project
    ) -> None:
        """Expired subscription → alert with /subscription pointer."""
        from datetime import timedelta

        user.subscription_expires_at = utcnow() - timedelta(days=1)
        await session.commit()
        update = make_update(callback_data=f"v2p:gen:{project.id}")
        await proposal_generate(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")

    async def test_send_twice_is_idempotent(
        self, session_factory, session: AsyncSession, user, portfolio, project
    ) -> None:
        """Second «Отправлено» does not duplicate CRM entries."""
        proposal = Proposal(
            project_id=project.id,
            user_id=user.id,
            generated_text="т",
            status=ProposalStatus.SENT,
            sent_at=utcnow(),
        )
        session.add(proposal)
        await session.commit()
        update = make_update(callback_data=f"v2p:send:{proposal.id}")
        await proposal_send(update, make_context())
        answer_text = update.callback_query.answer.await_args.args[0]
        assert "Уже" in answer_text

    async def test_hide_deletes_card(self, session_factory, user) -> None:
        """🙈 Скрыть removes the notification message."""
        update = make_update(callback_data="v2p:hide:1")
        await proposal_hide(update, make_context())
        update.callback_query.message.delete.assert_awaited()

    async def test_cases_lists_relevant_portfolio(
        self, session_factory, user, portfolio, project, monkeypatch
    ) -> None:
        """🧩 Кейсы под заказ (§3.6) — cases without LLM intro."""
        monkeypatch.setattr(
            proposals_module, "get_default_llm_client", lambda: None
        )
        update = make_update(callback_data=f"v2p:cases:{project.id}")
        await proposal_cases(update, make_context())
        text = update.callback_query.message.reply_text.await_args.args[0]
        assert "Кейсы под этот заказ" in text
        assert "Бот записи для барбершопа" in text

    async def test_cases_denied_without_portfolio(
        self, session_factory, user, project
    ) -> None:
        """No portfolio → alert pointing to /portfolio."""
        update = make_update(callback_data=f"v2p:cases:{project.id}")
        await proposal_cases(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")


class TestPortfolioHandlers:
    async def test_list_and_delete(
        self, session_factory, session: AsyncSession, user, portfolio
    ) -> None:
        """/portfolio lists cases; 🗑 removes one."""
        update = make_update(text="/portfolio")
        await portfolio_command(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "Бот записи для барбершопа" in text

        item_id = portfolio[0].id
        update = make_update(callback_data=f"v2pf:del:{item_id}")
        await portfolio_delete(update, make_context())
        async with session_factory() as check:
            left = (await check.execute(select(PortfolioItem))).scalars().all()
        assert len(left) == 1

    async def test_add_start_and_cancel(self, session_factory, user) -> None:
        """➕ Добавить starts the conversation; /cancel aborts cleanly."""
        update = make_update(callback_data="v2pf:add")
        context = make_context()
        assert await portfolio_add_start(update, context) == P_TITLE
        context.user_data["v2_pf_title"] = "x"
        cancel_update = make_update(text="/cancel")
        assert await portfolio_add_cancel(cancel_update, context) == (
            ConversationHandler.END
        )
        assert "v2_pf_title" not in context.user_data


class TestSourcesHandlers:
    async def test_menu_toggle_delete(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """Menu renders; toggle pauses; delete removes."""
        connection = ExchangeConnection(user_id=user.id, platform=Platform.KWORK)
        session.add(connection)
        await session.commit()

        update = make_update(callback_data="v2s:menu")
        await sources_menu(update, make_context())
        assert update.callback_query.edit_message_text.await_count == 1

        update = make_update(callback_data=f"v2s:toggle:{connection.id}")
        await source_toggle(update, make_context())
        async with session_factory() as check:
            row = await check.get(ExchangeConnection, connection.id)
        assert row is not None and row.status is ConnectionStatus.PAUSED

        update = make_update(callback_data=f"v2s:del:{connection.id}")
        await source_delete(update, make_context())
        async with session_factory() as check:
            left = (
                (await check.execute(select(ExchangeConnection))).scalars().all()
            )
        assert left == []


class TestOnboardingEdges:
    async def test_invalid_tax_reasked(self, session_factory) -> None:
        """Nonsense tax → stay in TAX state."""
        update = make_update(telegram_id=888003, text="/radar")
        context = make_context()
        await radar_entry(update, context)
        bad = make_update(telegram_id=888003, text="сто")
        assert await onboarding_tax(bad, context) == TAX

    async def test_cancel(self, session_factory) -> None:
        """/cancel ends the conversation politely."""
        update = make_update(text="/cancel")
        assert await onboarding_cancel(update, make_context()) == (
            ConversationHandler.END
        )


class TestSubscriptionEdges:
    async def test_callback_path(self, session_factory, user) -> None:
        """⭐ Подписка button edits the message."""
        update = make_update(callback_data="v2sub:info")
        await subscription_info(update, make_context())
        assert update.callback_query.edit_message_text.await_count == 1

    async def test_grant_bad_args(self, session_factory, user) -> None:
        """Malformed /grant explains the format."""
        update = make_update(telegram_id=OWNER_ID, text="/grant")
        await grant_subscription(update, make_context(args=["nonsense"]))
        reply = update.message.reply_text.await_args.args[0]
        assert "Формат" in reply

    async def test_grant_unknown_user(self, session_factory, user) -> None:
        """/grant for a user who never started the bot."""
        update = make_update(telegram_id=OWNER_ID, text="/grant")
        await grant_subscription(
            update, make_context(args=["424242", "pro", "30"])
        )
        reply = update.message.reply_text.await_args.args[0]
        assert "не найден" in reply


class TestProposalGuards:
    async def test_edit_start_sets_pending(
        self, session_factory, session: AsyncSession, user, project
    ) -> None:
        """✏️ Редактировать arms the router key."""
        from bot.handlers.v2.proposals import proposal_edit_start

        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="т"
        )
        session.add(proposal)
        await session.commit()
        context = make_context()
        update = make_update(callback_data=f"v2p:edit:{proposal.id}")
        await proposal_edit_start(update, context)
        assert context.user_data["v2_edit_proposal"] == proposal.id
        assert update.callback_query.message.reply_text.await_count == 1

    async def test_edit_unknown_proposal(self, session_factory, user) -> None:
        """Editing a missing draft fails softly."""
        from bot.handlers.v2.proposals import apply_proposal_edit

        context = make_context()
        context.user_data["v2_edit_proposal"] = 424242
        update = make_update(text="новый текст")
        await apply_proposal_edit(update, context, "новый текст")
        reply = update.message.reply_text.await_args.args[0]
        assert "не найден" in reply

    async def test_send_respects_crm_limit(
        self, session_factory, session: AsyncSession, user, portfolio, project
    ) -> None:
        """§7: Basic CRM cap — proposal sent, client NOT created."""
        from core.models import Client, PipelineStage

        user.subscription_tier = SubscriptionTier.BASIC
        for i in range(15):
            session.add(
                Client(
                    user_id=user.id,
                    name=f"c{i}",
                    pipeline_stage=PipelineStage.NEGOTIATION,
                )
            )
        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="т"
        )
        session.add(proposal)
        await session.commit()

        update = make_update(callback_data=f"v2p:send:{proposal.id}")
        await proposal_send(update, make_context())
        async with session_factory() as check:
            sent = await check.get(Proposal, proposal.id)
            clients = (await check.execute(select(Client))).scalars().all()
        assert sent is not None and sent.status is ProposalStatus.SENT
        assert len(clients) == 15  # no new card
        reply = update.callback_query.message.reply_text.await_args.args[0]
        assert "Лимит" in reply

    async def test_cases_with_llm_intro(
        self, session_factory, user, portfolio, project, monkeypatch
    ) -> None:
        """§3.6: adapted intro line rendered when LLM is available."""
        monkeypatch.setattr(
            proposals_module,
            "get_default_llm_client",
            lambda: FakeLLM(["Делал похожего бота записи для барбершопа."]),
        )
        update = make_update(callback_data=f"v2p:cases:{project.id}")
        await proposal_cases(update, make_context())
        text = update.callback_query.message.reply_text.await_args.args[0]
        assert "барбершоп" in text

    async def test_cases_denied_for_basic(
        self, session_factory, session: AsyncSession, user, portfolio, project
    ) -> None:
        """§7: адаптация портфолио — Pro/Business only."""
        user.subscription_tier = SubscriptionTier.BASIC
        await session.commit()
        update = make_update(callback_data=f"v2p:cases:{project.id}")
        await proposal_cases(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")


class TestSourceGuards:
    async def test_tg_channel_limit_for_basic(
        self, session_factory, session: AsyncSession, user
    ) -> None:
        """§7: Basic — до 5 TG-каналов, шестой отклоняется."""
        from bot.handlers.v2.sources import source_add

        user.subscription_tier = SubscriptionTier.BASIC
        for i in range(5):
            session.add(
                ExchangeConnection(
                    user_id=user.id,
                    platform=Platform.TG_CHANNEL,
                    settings={"channel": f"@ch{i}"},
                )
            )
        await session.commit()
        update = make_update(callback_data="v2s:add:tg")
        context = make_context()
        await source_add(update, context)
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")
        assert "v2_add_channel" not in context.user_data

    async def test_toggle_unknown_connection(self, session_factory, user) -> None:
        """Unknown id → alert."""
        update = make_update(callback_data="v2s:toggle:424242")
        await source_toggle(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")

    async def test_bad_channel_username_rejected(
        self, session_factory, user
    ) -> None:
        """Too-short username is not saved."""
        from bot.handlers.v2.sources import add_channel_from_text

        update = make_update(text="@a")
        await add_channel_from_text(update, make_context(), "@a")
        async with session_factory() as check:
            rows = (
                (await check.execute(select(ExchangeConnection))).scalars().all()
            )
        assert rows == []


class TestCrmGuards:
    async def test_stage_unknown_client(self, session_factory, user) -> None:
        """Stage change on a missing client → alert."""
        from bot.handlers.v2.crm_handlers import client_stage

        update = make_update(callback_data="v2c:stage:424242:proposal_sent")
        await client_stage(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")

    async def test_note_unknown_client(self, session_factory, user) -> None:
        """Note for a missing client fails softly."""
        from bot.handlers.v2.crm_handlers import apply_client_note

        context = make_context()
        context.user_data["v2_note_client"] = 424242
        update = make_update(text="заметка")
        await apply_client_note(update, context, "заметка")
        reply = update.message.reply_text.await_args.args[0]
        assert "не найден" in reply

    async def test_snooze_unknown_reminder(self, session_factory, user) -> None:
        """Snooze on a missing reminder → alert."""
        from bot.handlers.v2.crm_handlers import reminder_snooze

        update = make_update(callback_data="v2r:snooze:424242")
        await reminder_snooze(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")


class TestProposalNotFoundAndGuards:
    async def test_handlers_ignore_non_callback_updates(
        self, session_factory, user
    ) -> None:
        """Plain-text updates fall through every callback handler safely."""
        from bot.handlers.v2.proposals import (
            proposal_cases,
            proposal_edit_start,
            proposal_generate,
            proposal_hide,
            proposal_regenerate,
            proposal_send,
        )

        update = make_update(text="просто сообщение")
        context = make_context()
        for handler in (
            proposal_generate,
            proposal_regenerate,
            proposal_edit_start,
            proposal_send,
            proposal_hide,
            proposal_cases,
        ):
            await handler(update, context)  # no exceptions, no effects

    async def test_unknown_ids_alert(
        self, session_factory, user, portfolio
    ) -> None:
        """Unknown project/proposal ids → alerts, never crashes."""
        for data in ("v2p:gen:424242", "v2p:cases:424242"):
            update = make_update(callback_data=data)
            await proposal_generate(update, make_context()) if data.startswith(
                "v2p:gen"
            ) else await proposal_cases(update, make_context())
            assert update.callback_query.answer.await_args.kwargs.get(
                "show_alert"
            )

        update = make_update(callback_data="v2p:send:424242")
        await proposal_send(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")

        update = make_update(callback_data="v2p:regen:424242")
        await proposal_regenerate(update, make_context())
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")

    async def test_regenerate_llm_error_is_soft(
        self,
        session_factory,
        session: AsyncSession,
        user,
        portfolio,
        project,
        monkeypatch,
    ) -> None:
        """LLM outage during regen → friendly reply, draft intact."""

        class BoomLLM(OpenRouterClient):
            def __init__(self) -> None:
                super().__init__(api_key="x")

            async def chat(self, *args: object, **kwargs: object) -> str:
                raise LLMError("down")

        proposal = Proposal(
            project_id=project.id, user_id=user.id, generated_text="стабильный"
        )
        session.add(proposal)
        await session.commit()
        monkeypatch.setattr(
            proposals_module, "get_default_llm_client", lambda: BoomLLM()
        )
        update = make_update(callback_data=f"v2p:regen:{proposal.id}")
        await proposal_regenerate(update, make_context())
        async with session_factory() as check:
            row = await check.get(Proposal, proposal.id)
        assert row is not None and row.generated_text == "стабильный"

    async def test_cases_intro_llm_error_still_lists_cases(
        self, session_factory, user, portfolio, project, monkeypatch
    ) -> None:
        """Intro generation failure degrades gracefully (§3.6)."""

        class BoomLLM(OpenRouterClient):
            def __init__(self) -> None:
                super().__init__(api_key="x")

            async def chat(self, *args: object, **kwargs: object) -> str:
                raise LLMError("down")

        monkeypatch.setattr(
            proposals_module, "get_default_llm_client", lambda: BoomLLM()
        )
        update = make_update(callback_data=f"v2p:cases:{project.id}")
        await proposal_cases(update, make_context())
        text = update.callback_query.message.reply_text.await_args.args[0]
        assert "Кейсы под этот заказ" in text
