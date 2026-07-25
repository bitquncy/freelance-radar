"""Telegram Payments tests — §7 pricing, idempotency, validation, weekly report."""
from datetime import timedelta
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.v2.payments import (
    buy_subscription,
    on_successful_payment,
    precheckout,
)
from core import billing
from core.models import (
    Client,
    PaymentStatus,
    Project,
    ProjectAnalysis,
    Proposal,
    ProposalStatus,
    Subscription,
    SubscriptionTier,
    User,
    utcnow,
)
from monitoring.worker import run_weekly_report_tick
from tests.unit.v2.conftest import make_context, make_update


class TestPayloadAndPricing:
    def test_roundtrip_and_prices(self) -> None:
        """Payload encodes tier+period; price always comes from §7 table."""
        for tier, price in ((SubscriptionTier.BASIC, 299),
                            (SubscriptionTier.PRO, 599),
                            (SubscriptionTier.BUSINESS, 999)):
            intent = billing.parse_payload(billing.build_payload(tier))
            assert intent.tier is tier
            assert intent.amount_rub == price
            assert intent.amount_kopecks == price * 100
            assert intent.days == billing.SUBSCRIPTION_DAYS

    def test_bad_payloads_rejected(self) -> None:
        """Foreign/malformed payloads never validate."""
        for bad in ("", "junk", "v2sub:trial:30", "v2sub:pro:999",
                    "v2sub:pro", "other:pro:30", "v2sub:gold:30"):
            with pytest.raises(billing.PaymentError):
                billing.parse_payload(bad)

    def test_amount_validation(self) -> None:
        """Client-reported totals are checked against the §7 price."""
        intent = billing.parse_payload(billing.build_payload(SubscriptionTier.PRO))
        billing.validate_paid_amount(intent, 59900)  # ok
        with pytest.raises(billing.PaymentError):
            billing.validate_paid_amount(intent, 100)  # underpaid
        with pytest.raises(billing.PaymentError):
            billing.validate_paid_amount(intent, 99900)  # wrong tier price


class TestApplyPaidSubscription:
    async def test_activation_sets_tier_and_expiry(
        self, session: AsyncSession, user: User
    ) -> None:
        """A paid charge activates the tier for 30 days."""
        intent = billing.parse_payload(billing.build_payload(SubscriptionTier.PRO))
        sub, applied = await billing.apply_paid_subscription(
            session, user, intent, charge_id="chg-1"
        )
        await session.commit()
        assert applied is True
        assert sub is not None and sub.status is PaymentStatus.PAID
        assert user.subscription_tier is SubscriptionTier.PRO
        assert user.subscription_expires_at is not None
        delta = user.subscription_expires_at - utcnow()
        assert timedelta(days=29) < delta <= timedelta(days=30)

    async def test_same_tier_extends_from_current_expiry(
        self, session: AsyncSession, user: User
    ) -> None:
        """Same-tier renewal never loses already-paid days."""
        user.subscription_tier = SubscriptionTier.PRO
        user.subscription_expires_at = utcnow() + timedelta(days=10)
        intent = billing.parse_payload(billing.build_payload(SubscriptionTier.PRO))
        await billing.apply_paid_subscription(session, user, intent, "chg-2")
        await session.commit()
        delta = user.subscription_expires_at - utcnow()
        assert timedelta(days=39) < delta <= timedelta(days=40)

    async def test_tier_switch_starts_now(
        self, session: AsyncSession, user: User
    ) -> None:
        """Switching tiers starts a fresh 30-day period."""
        user.subscription_tier = SubscriptionTier.BASIC
        user.subscription_expires_at = utcnow() + timedelta(days=300)
        intent = billing.parse_payload(
            billing.build_payload(SubscriptionTier.BUSINESS)
        )
        await billing.apply_paid_subscription(session, user, intent, "chg-3")
        await session.commit()
        assert user.subscription_tier is SubscriptionTier.BUSINESS
        delta = user.subscription_expires_at - utcnow()
        assert delta <= timedelta(days=30)

    async def test_duplicate_charge_is_ignored(
        self, session: AsyncSession, user: User
    ) -> None:
        """AUDIT-grade idempotency: same charge id applies exactly once."""
        intent = billing.parse_payload(billing.build_payload(SubscriptionTier.PRO))
        await billing.apply_paid_subscription(session, user, intent, "chg-dup")
        await session.commit()
        first_expiry = user.subscription_expires_at

        _, applied = await billing.apply_paid_subscription(
            session, user, intent, "chg-dup"
        )
        await session.commit()
        assert applied is False
        assert user.subscription_expires_at == first_expiry
        rows = (await session.execute(select(Subscription))).scalars().all()
        assert len(rows) == 1


def _payment_update(
    payload: str,
    total_amount: int,
    charge_id: str = "tg-charge-1",
    telegram_id: int = 555001,
) -> SimpleNamespace:
    message = SimpleNamespace(
        successful_payment=SimpleNamespace(
            invoice_payload=payload,
            total_amount=total_amount,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id="prov-1",
        ),
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=telegram_id, username="payer"),
        message=message,
        callback_query=None,
        pre_checkout_query=None,
    )


def _precheckout_update(payload: str, total_amount: int) -> SimpleNamespace:
    return SimpleNamespace(
        pre_checkout_query=SimpleNamespace(
            invoice_payload=payload,
            total_amount=total_amount,
            answer=AsyncMock(),
        )
    )


class TestPaymentHandlers:
    async def test_buy_without_token_shows_alert(
        self, session_factory, user, monkeypatch
    ) -> None:
        """Payments ship dark until the provider token is configured."""
        from config import get_config

        monkeypatch.setattr(get_config(), "PAYMENT_PROVIDER_TOKEN", "")
        update = make_update(callback_data="v2sub:buy:pro")
        context = make_context()
        context.bot = SimpleNamespace(send_invoice=AsyncMock())
        await buy_subscription(update, context)
        assert update.callback_query.answer.await_args.kwargs.get("show_alert")
        context.bot.send_invoice.assert_not_awaited()

    async def test_buy_sends_invoice_with_spec_price(
        self, session_factory, user, monkeypatch
    ) -> None:
        """Invoice carries the §7 price in kopecks and our payload."""
        from config import get_config

        monkeypatch.setattr(
            get_config(), "PAYMENT_PROVIDER_TOKEN", "live-token"
        )
        update = make_update(callback_data="v2sub:buy:business")
        context = make_context()
        context.bot = SimpleNamespace(send_invoice=AsyncMock())
        await buy_subscription(update, context)
        kwargs = context.bot.send_invoice.await_args.kwargs
        assert kwargs["payload"] == "v2sub:business:30"
        assert kwargs["provider_token"] == "live-token"
        assert kwargs["prices"][0].amount == 999 * 100

    async def test_precheckout_ok_and_reject(self, session_factory) -> None:
        """Valid order approved; foreign payload rejected within the flow."""
        good = _precheckout_update("v2sub:pro:30", 59900)
        await precheckout(good, make_context())  # type: ignore[arg-type]
        assert good.pre_checkout_query.answer.await_args.kwargs["ok"] is True

        bad = _precheckout_update("v2sub:pro:30", 100)
        await precheckout(bad, make_context())  # type: ignore[arg-type]
        assert bad.pre_checkout_query.answer.await_args.kwargs["ok"] is False

    async def test_successful_payment_activates(
        self, session_factory, user
    ) -> None:
        """The happy path: charge confirmed → tier active, receipt reply."""
        update = _payment_update("v2sub:pro:30", 59900, "tg-ok-1")
        await on_successful_payment(update, make_context())  # type: ignore[arg-type]
        async with session_factory() as check:
            row = (
                await check.execute(
                    select(User).where(User.telegram_id == 555001)
                )
            ).scalar_one()
            subs = (await check.execute(select(Subscription))).scalars().all()
        assert row.subscription_tier is SubscriptionTier.PRO
        assert len(subs) == 1 and subs[0].payment_charge_id == "tg-ok-1"
        reply = update.message.reply_text.await_args.args[0]
        assert "Оплата прошла" in reply

    async def test_successful_payment_duplicate_update(
        self, session_factory, user
    ) -> None:
        """Telegram re-delivers updates — the second one must be a no-op."""
        first = _payment_update("v2sub:pro:30", 59900, "tg-dup-9")
        await on_successful_payment(first, make_context())  # type: ignore[arg-type]
        second = _payment_update("v2sub:pro:30", 59900, "tg-dup-9")
        await on_successful_payment(second, make_context())  # type: ignore[arg-type]
        async with session_factory() as check:
            subs = (await check.execute(select(Subscription))).scalars().all()
        assert len(subs) == 1
        reply = second.message.reply_text.await_args.args[0]
        assert "уже был учтён" in reply

    async def test_successful_payment_bad_payload_never_activates(
        self, session_factory, user
    ) -> None:
        """A charged-but-unrecognized order escalates, never auto-activates."""
        update = _payment_update("v2sub:pro:999", 59900, "tg-weird-1")
        await on_successful_payment(update, make_context())  # type: ignore[arg-type]
        async with session_factory() as check:
            row = (
                await check.execute(
                    select(User).where(User.telegram_id == 555001)
                )
            ).scalar_one()
            subs = (await check.execute(select(Subscription))).scalars().all()
        assert row.subscription_tier is SubscriptionTier.TRIAL  # unchanged
        assert subs == []
        reply = update.message.reply_text.await_args.args[0]
        assert "вручную" in reply


class NotifyRecorder:
    def __init__(self) -> None:
        self.sent: list = []

    async def __call__(
        self, application: object, chat_id: int, text: str, markup: object = None
    ) -> Optional[bool]:
        self.sent.append({"chat_id": chat_id, "text": text})
        return True


class TestWeeklyReport:
    async def test_report_sent_to_pro_with_activity(
        self, session_factory, session: AsyncSession, user: User, project: Project
    ) -> None:
        """§7: Pro gets the weekly digest with real numbers."""
        session.add(
            ProjectAnalysis(
                project_id=project.id, user_id=user.id, win_probability=77.0
            )
        )
        session.add(
            Proposal(
                project_id=project.id,
                user_id=user.id,
                generated_text="т",
                status=ProposalStatus.SENT,
                sent_at=utcnow(),
            )
        )
        session.add(Client(user_id=user.id, name="К"))
        await session.commit()

        notify = NotifyRecorder()
        delivered = await run_weekly_report_tick(
            None, session_factory=session_factory, notify=notify
        )
        assert delivered == 1
        text = notify.sent[0]["text"]
        assert "Неделя в FreelanceRadar" in text
        assert "77%" in text

    async def test_basic_and_silent_users_skipped(
        self, session_factory, session: AsyncSession, user: User
    ) -> None:
        """Basic has no weekly report (§7); empty weeks send nothing."""
        user.subscription_tier = SubscriptionTier.BASIC
        session.add(Client(user_id=user.id, name="К"))  # has activity but Basic
        quiet_pro = User(
            telegram_id=555777,
            subscription_tier=SubscriptionTier.PRO,
        )
        session.add(quiet_pro)  # Pro but zero activity
        await session.commit()

        notify = NotifyRecorder()
        delivered = await run_weekly_report_tick(
            None, session_factory=session_factory, notify=notify
        )
        assert delivered == 0
        assert notify.sent == []

    def test_weekly_job_registered(self) -> None:
        """The cron job lands in the scheduler with safe misfire settings."""
        from monitoring.worker import register_v2_jobs

        class FakeScheduler:
            def __init__(self) -> None:
                self.jobs: list = []

            def add_job(self, *args: object, **kwargs: object) -> None:
                self.jobs.append(kwargs)

        scheduler = FakeScheduler()
        register_v2_jobs(scheduler, application=None)  # type: ignore[arg-type]
        weekly = next(j for j in scheduler.jobs if j["id"] == "v2_weekly_report")
        assert weekly["day_of_week"] == "mon"
        assert weekly["coalesce"] is True
