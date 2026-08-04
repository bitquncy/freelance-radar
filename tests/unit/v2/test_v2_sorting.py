"""Tests for task_0004: per-user order of delivered/listed order cards.

Covers the pure sort engine (each mode + defaults), the User model column,
the /sort command, and the worker's per-user notification delivery order.
"""

import re
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    NotificationDelivery,
    ProjectAnalysis,
    SortPreference,
    User,
    utcnow,
)
from core.sorting import sort_project_cards
from bot.handlers.v2.sort_preference import set_sort_preference
from monitoring.worker import _drain_pending_notifications
from tests.unit.v2.conftest import make_context, make_project, make_update


def _project(posted_at):
    """A lightweight stand-in exposing only what the engine reads."""
    return SimpleNamespace(posted_at=posted_at)


def _analysis(win=None, profit=None):
    return SimpleNamespace(win_probability=win, profitability_index=profit)


def _item(project, analysis=None):
    return SimpleNamespace(project=project, analysis=analysis)


class TestSortEngine:
    def test_default_preserves_order(self) -> None:
        items = [
            _item(_project(utcnow()), _analysis(50, 1.0)),
            _item(_project(utcnow()), _analysis(90, 2.0)),
        ]
        assert sort_project_cards(items, SortPreference.DEFAULT) is not items
        assert sort_project_cards(items, SortPreference.DEFAULT) == items
        assert sort_project_cards(items, None) == items

    def test_score_desc(self) -> None:
        low = _item(_project(utcnow()), _analysis(30, 1.0))
        high = _item(_project(utcnow()), _analysis(90, 0.5))
        unknown = _item(_project(utcnow()), _analysis(None, 2.0))
        result = sort_project_cards([low, high, unknown], SortPreference.SCORE)
        assert [r.analysis.win_probability for r in result] == [90, 30, None]

    def test_profitability_desc(self) -> None:
        low = _item(_project(utcnow()), _analysis(90, 0.3))
        high = _item(_project(utcnow()), _analysis(10, 3.0))
        unknown = _item(_project(utcnow()), _analysis(50, None))
        result = sort_project_cards([low, high, unknown], SortPreference.PROFITABILITY)
        assert [r.analysis.profitability_index for r in result] == [3.0, 0.3, None]

    def test_freshness_desc(self) -> None:
        base = utcnow()
        old = _item(_project(base - timedelta(hours=5)))
        mid = _item(_project(base - timedelta(hours=2)))
        new = _item(_project(base))
        result = sort_project_cards([old, mid, new], SortPreference.FRESHNESS)
        assert result == [new, mid, old]

    def test_string_preference_accepted(self) -> None:
        a = _item(_project(utcnow()), _analysis(20))
        b = _item(_project(utcnow()), _analysis(80))
        assert [
            r.analysis.win_probability for r in sort_project_cards([a, b], "score")
        ] == [80, 20]

    def test_ties_stay_in_insertion_order(self) -> None:
        a = _item(_project(utcnow()), _analysis(50))
        b = _item(_project(utcnow()), _analysis(50))
        c = _item(_project(utcnow()), _analysis(50))
        assert sort_project_cards([a, b, c], SortPreference.SCORE) == [a, b, c]


class TestUserModel:
    async def test_default_is_default(self, session: AsyncSession, user: User) -> None:
        assert (
            user.sort_preference or SortPreference.DEFAULT
        ) is SortPreference.DEFAULT

    async def test_preference_roundtrips(
        self, session_factory, session: AsyncSession, user: User
    ) -> None:
        user.sort_preference = SortPreference.FRESHNESS
        await session.commit()
        async with session_factory() as check:
            loaded = await check.get(User, user.id)
            assert loaded.sort_preference is SortPreference.FRESHNESS


class TestSortCommand:
    async def test_sets_preference(self, session_factory, session, user) -> None:
        update = make_update()
        await set_sort_preference(update, make_context(args=["score"]))
        update.message.reply_text.assert_awaited_once()
        async with session_factory() as check:
            assert (
                await check.get(User, user.id)
            ).sort_preference is SortPreference.SCORE

    async def test_default_restores_default(
        self, session_factory, session, user
    ) -> None:
        user.sort_preference = SortPreference.PROFITABILITY
        await session.commit()
        update = make_update()
        await set_sort_preference(update, make_context(args=["default"]))
        update.message.reply_text.assert_awaited_once()
        async with session_factory() as check:
            assert (
                await check.get(User, user.id)
            ).sort_preference is SortPreference.DEFAULT

    async def test_unknown_arg_shows_help_not_error(
        self, session_factory, session, user
    ) -> None:
        user.sort_preference = SortPreference.SCORE
        await session.commit()
        update = make_update()
        await set_sort_preference(update, make_context(args=["bogus"]))
        update.message.reply_text.assert_awaited_once()
        async with session_factory() as check:
            assert (
                await check.get(User, user.id)
            ).sort_preference is SortPreference.SCORE


class _OrderRecorder:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def __call__(self, application, chat_id, text, markup=None) -> None:
        self.sent.append(text)


def _probabilities(messages: list[str]) -> list[int]:
    out = []
    for text in messages:
        m = re.search(r"Вероятность получить заказ:\s*<b>(\d+)%</b>", text)
        assert m is not None, text
        out.append(int(m.group(1)))
    return out


class TestWorkerDeliveryOrder:
    async def test_score_preference_orders_delivery(
        self, session_factory, session: AsyncSession, user: User
    ) -> None:
        """A user with /sort score gets queued cards sent by win probability desc."""
        user.sort_preference = SortPreference.SCORE
        score_by_ext = {"ord-a": 40, "ord-b": 90, "ord-c": 60}
        for ext, score in score_by_ext.items():
            project = make_project(external_id=ext)
            session.add(project)
            await session.flush()
            analysis = ProjectAnalysis(
                project_id=project.id,
                user_id=user.id,
                win_probability=score,
            )
            session.add(analysis)
            await session.flush()
            session.add(
                NotificationDelivery(
                    analysis_id=analysis.id,
                    user_id=user.id,
                    project_id=project.id,
                    chat_id=user.telegram_id,
                )
            )
        await session.commit()

        recorder = _OrderRecorder()
        sent, failed = await _drain_pending_notifications(
            session_factory, None, recorder
        )
        assert sent == 3
        assert failed == 0
        assert _probabilities(recorder.sent) == [90, 60, 40]

    async def test_default_keeps_insertion_order(
        self, session_factory, session: AsyncSession, user: User
    ) -> None:
        """With no preference, delivery order is unchanged (as-arrived)."""
        score_by_ext = {"ord-a": 90, "ord-b": 30, "ord-c": 60}
        for ext, score in score_by_ext.items():
            project = make_project(external_id=ext)
            session.add(project)
            await session.flush()
            analysis = ProjectAnalysis(
                project_id=project.id,
                user_id=user.id,
                win_probability=score,
            )
            session.add(analysis)
            await session.flush()
            session.add(
                NotificationDelivery(
                    analysis_id=analysis.id,
                    user_id=user.id,
                    project_id=project.id,
                    chat_id=user.telegram_id,
                )
            )
        await session.commit()

        recorder = _OrderRecorder()
        sent, _ = await _drain_pending_notifications(session_factory, None, recorder)
        assert sent == 3
        assert _probabilities(recorder.sent) == [90, 30, 60]  # id order preserved
