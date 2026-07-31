"""UX + single-plan subscription tests: dashboard, paywall, expiry nudges.

Covers the owner-facing behaviour changes:
    * one plan at 300 ₽/мес with a 7-day free trial;
    * a dashboard that always tells the user what to do next;
    * a paywall that explains what stopped and how to restore it;
    * expiry reminders that fire once per period, never nightly.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.v2.common import NO_ACCESS_TEXT, deny_no_access, paywall_text
from bot.handlers.v2.menu import dashboard_text, main_menu_keyboard, show_help, show_menu
from bot.handlers.v2.subscription import subscription_info
from core import tariffs
from core.models import (
    ConnectionStatus,
    ExchangeConnection,
    Platform,
    SubscriptionTier,
    User,
    utcnow,
)
from monitoring.worker import EXPIRY_WARN_DAYS, run_expiry_reminders_tick
from tests.unit.v2.conftest import make_context, make_update


class TestDashboard:
    async def test_menu_shows_status_and_next_step(
        self, session_factory, user
    ) -> None:
        """/menu renders live counters and a concrete next action."""
        update = make_update(text="/menu")
        await show_menu(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "FreelanceRadar" in text
        assert "Бесплатный период" in text  # trial user fixture
        # No sources yet → the hint must point at sources, not at payment.
        assert "Подключите хотя бы один источник" in text
        assert "Источники:</b> 0" in text

    async def test_menu_hint_moves_to_portfolio_once_sources_exist(
        self, session: AsyncSession, session_factory, user
    ) -> None:
        """With a source connected the next step becomes the portfolio."""
        session.add(
            ExchangeConnection(
                user_id=user.id,
                platform=Platform.KWORK,
                status=ConnectionStatus.ACTIVE,
            )
        )
        await session.commit()
        update = make_update(text="/menu")
        await show_menu(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "портфолио" in text.lower()
        assert "Сканирование" in text

    def test_dashboard_asks_expired_user_to_renew(self) -> None:
        """An expired subscription outranks other hints."""
        expired = User(
            telegram_id=1,
            target_hourly_rate=1500,
            subscription_tier=SubscriptionTier.PRO,
            subscription_expires_at=utcnow() - timedelta(days=1),
        )
        text = dashboard_text(expired, sources=2, portfolio=3, clients=1, sent=4)
        assert "Продлите подписку" in text
        assert "Сканирование не активно" in text

    def test_onboarding_button_only_for_new_users(self) -> None:
        """The «настроить профиль» CTA disappears after onboarding."""
        fresh = str(main_menu_keyboard(onboarded=False).inline_keyboard)
        done = str(main_menu_keyboard(onboarded=True).inline_keyboard)
        assert "v2:onboard" in fresh
        assert "v2:onboard" not in done

    async def test_help_screen_has_way_back(self, session_factory) -> None:
        """Help is reachable and never a dead end."""
        update = make_update(callback_data="v2:help")
        await show_help(update, make_context())
        text = update.callback_query.edit_message_text.await_args.args[0]
        markup = update.callback_query.edit_message_text.await_args.kwargs[
            "reply_markup"
        ]
        assert "Как работает FreelanceRadar" in text
        assert "300 ₽/мес" in text
        assert "v2:menu" in str(markup.inline_keyboard)


class TestPaywall:
    def test_texts_mention_price_trial_and_data_safety(self) -> None:
        """The paywall sells honestly: price, and that nothing was deleted."""
        assert "300" in NO_ACCESS_TEXT
        assert len(NO_ACCESS_TEXT) <= 200  # Telegram alert limit
        body = paywall_text()
        assert "300 ₽/мес" in body
        # Reassures the user that nothing was deleted behind the paywall.
        assert "CRM" in body and "целы" in body.lower()

    async def test_deny_sends_alert_and_pay_button(self, session_factory) -> None:
        """A blocked button answers with an alert AND a payable card."""
        update = make_update(callback_data="v2p:make:1")
        await deny_no_access(update)
        update.callback_query.answer.assert_awaited()
        assert update.callback_query.answer.await_args.kwargs["show_alert"] is True
        markup = update.callback_query.message.reply_text.await_args.kwargs[
            "reply_markup"
        ]
        assert f"v2sub:buy:{tariffs.PRIMARY_TIER.value}" in str(
            markup.inline_keyboard
        )

    async def test_subscription_card_for_expired_user(
        self, session: AsyncSession, session_factory, user
    ) -> None:
        """Expired users see a paused-access card with a single renew button."""
        user.subscription_expires_at = utcnow() - timedelta(days=1)
        await session.commit()
        update = make_update(text="/subscription")
        await subscription_info(update, make_context())
        call = update.message.reply_text.await_args
        text, markup = call.args[0], call.kwargs["reply_markup"]
        assert "Доступ приостановлен" in text
        buttons = markup.inline_keyboard
        assert len(buttons[0]) == 1 and "300 ₽" in buttons[0][0].text


class TestExpiryReminders:
    async def test_warns_before_expiry_once(
        self, session: AsyncSession, session_factory, user
    ) -> None:
        """A trial ending inside the warning window gets exactly one nudge."""
        user.subscription_expires_at = utcnow() + timedelta(
            days=EXPIRY_WARN_DAYS - 1
        )
        await session.commit()
        sent: list = []

        async def notify(app, chat_id, text, markup=None):
            sent.append((chat_id, text))
            return True

        first = await run_expiry_reminders_tick(
            None, session_factory=session_factory, notify=notify
        )
        second = await run_expiry_reminders_tick(
            None, session_factory=session_factory, notify=notify
        )
        assert (first, second) == (1, 0)  # idempotent: never a daily nag
        assert "Бесплатный период заканчивается" in sent[0][1]
        assert "300" in sent[0][1]

        async with session_factory() as check:
            row = (
                await check.execute(
                    select(User).where(User.telegram_id == user.telegram_id)
                )
            ).scalar_one()
        assert row.expiry_notified_at is not None

    async def test_expired_user_gets_access_paused_notice(
        self, session: AsyncSession, session_factory, user
    ) -> None:
        """After expiry the message explains what stopped and what survived."""
        user.subscription_tier = SubscriptionTier.PRO
        user.subscription_expires_at = utcnow() - timedelta(hours=2)
        await session.commit()
        sent: list = []

        async def notify(app, chat_id, text, markup=None):
            sent.append(text)
            return True

        assert (
            await run_expiry_reminders_tick(
                None, session_factory=session_factory, notify=notify
            )
            == 1
        )
        assert "Доступ приостановлен" in sent[0]
        assert "CRM" in sent[0]

    async def test_healthy_subscription_is_not_pinged(
        self, session: AsyncSession, session_factory, user
    ) -> None:
        """Plenty of time left → silence."""
        user.subscription_expires_at = utcnow() + timedelta(days=20)
        await session.commit()

        async def notify(app, chat_id, text, markup=None):  # pragma: no cover
            raise AssertionError("must not notify a healthy subscription")

        assert (
            await run_expiry_reminders_tick(
                None, session_factory=session_factory, notify=notify
            )
            == 0
        )

    async def test_manual_grant_without_expiry_is_skipped(
        self, session: AsyncSession, session_factory, user
    ) -> None:
        """Lifetime/manual grants have no expiry and must never be nagged."""
        user.subscription_expires_at = None
        await session.commit()

        async def notify(app, chat_id, text, markup=None):  # pragma: no cover
            raise AssertionError("must not notify a user without an expiry")

        assert (
            await run_expiry_reminders_tick(
                None, session_factory=session_factory, notify=notify
            )
            == 0
        )


class TestPublicEntryPoints:
    """/start and /help must be open to paying users, not owner-only.

    Regression: both commands were decorated with @owner_only, so every
    non-owner customer got "⛔ У вас нет доступа" on the very first screen —
    a hard blocker for a paid multi-tenant bot.
    """

    async def test_start_greets_a_non_owner_when_v2_is_on(
        self, session_factory, monkeypatch
    ) -> None:
        from config import get_config

        from bot.commands import start

        monkeypatch.setattr(get_config(), "RADAR_V2_ENABLED", True)
        update = make_update(telegram_id=424242, text="/start")
        await start(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "нет доступа" not in text
        assert "Добро пожаловать" in text
        assert "300" in text and "7 дней" in text  # trial + price up front

    async def test_help_is_open_and_explains_the_product(
        self, session_factory, monkeypatch
    ) -> None:
        from config import get_config

        from bot.commands import help_command

        monkeypatch.setattr(get_config(), "RADAR_V2_ENABLED", True)
        update = make_update(telegram_id=424242, text="/help")
        await help_command(update, make_context())
        text = update.message.reply_text.await_args.args[0]
        assert "нет доступа" not in text
        assert "Как работает FreelanceRadar" in text

    async def test_legacy_mode_still_owner_only(
        self, session_factory, monkeypatch
    ) -> None:
        """With V2 off the legacy single-owner bot stays locked down."""
        from config import get_config

        from bot.commands import start

        monkeypatch.setattr(get_config(), "RADAR_V2_ENABLED", False)
        update = make_update(telegram_id=424242, text="/start")
        await start(update, make_context())
        assert "нет доступа" in update.message.reply_text.await_args.args[0]
