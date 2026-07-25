"""Collector dedup tests — §3.1: exact key + fuzzy repost matching."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Platform, Project
from monitoring.adapters.base import RawListing
from monitoring.collector import (
    Collector,
    budgets_close,
    is_fuzzy_duplicate,
    normalize_title,
    titles_similar,
)
from tests.unit.v2.conftest import make_project


def listing(
    external_id: str = "l-1",
    source: Platform = Platform.KWORK,
    title: str = "Нужен Telegram-бот для записи клиентов",
    budget_min: int = 20000,
) -> RawListing:
    return RawListing(
        source=source,
        external_id=external_id,
        title=title,
        description_raw="описание",
        budget_min=budget_min,
    )


class TestFuzzyHelpers:
    def test_normalize_title_strips_noise(self) -> None:
        """Emoji/punctuation/case must not defeat dedup."""
        a = normalize_title("🔥СРОЧНО!!! Нужен Telegram-бот, для записи")
        b = normalize_title("срочно нужен telegram бот для записи")
        assert a == b

    def test_titles_similar_catches_repost(self) -> None:
        """Slightly edited repost is still the same order."""
        assert titles_similar(
            "Нужен Telegram-бот для записи клиентов",
            "🔥Нужен Telegram-бот для записи клиентов, срочно!",
        )
        assert not titles_similar("Нужен бот", "Требуется дизайн логотипа")

    def test_budgets_close(self) -> None:
        """±10% budget tolerance; both-missing counts as close."""
        assert budgets_close(20000, 21000)
        assert not budgets_close(20000, 40000)
        assert budgets_close(None, None)
        assert not budgets_close(20000, None)

    def test_is_fuzzy_duplicate(self) -> None:
        """Title AND budget must both match (§3.1)."""
        project = make_project()
        same = listing(external_id="other-id")
        assert is_fuzzy_duplicate(same, project)
        different_budget = listing(external_id="x", budget_min=90000)
        assert not is_fuzzy_duplicate(different_budget, project)


class TestCollector:
    async def test_inserts_new_projects(self, session: AsyncSession) -> None:
        """Fresh listings become Project rows."""
        result = await Collector().collect(
            session, [listing("a-1"), listing("a-2", title="Совсем другой заказ")]
        )
        await session.commit()
        assert len(result.new_projects) == 2
        rows = (await session.execute(select(Project))).scalars().all()
        assert {r.external_id for r in rows} == {"a-1", "a-2"}

    async def test_exact_duplicate_skipped(self, session: AsyncSession) -> None:
        """(source, external_id) already in DB → skip."""
        collector = Collector()
        await collector.collect(session, [listing("d-1")])
        await session.commit()
        result = await collector.collect(session, [listing("d-1")])
        await session.commit()
        assert result.new_projects == []
        assert result.duplicates_exact == 1

    async def test_duplicate_within_one_batch_skipped(
        self, session: AsyncSession
    ) -> None:
        """The same listing twice in one fetch is inserted once."""
        result = await Collector().collect(
            session, [listing("b-1"), listing("b-1")]
        )
        assert len(result.new_projects) == 1
        assert result.duplicates_exact == 1

    async def test_fuzzy_repost_across_channels_skipped(
        self, session: AsyncSession
    ) -> None:
        """§3.1: one order reposted to several channels → one project."""
        collector = Collector()
        await collector.collect(
            session,
            [
                RawListing(
                    source=Platform.TG_CHANNEL,
                    external_id="chan1-99",
                    title="Нужен парсер каталога товаров на Python",
                    budget_min=15000,
                )
            ],
        )
        await session.commit()
        result = await collector.collect(
            session,
            [
                RawListing(
                    source=Platform.TG_CHANNEL,
                    external_id="chan2-777",
                    title="🔥Нужен парсер каталога товаров на Python!",
                    budget_min=15500,
                )
            ],
        )
        await session.commit()
        assert result.new_projects == []
        assert result.duplicates_fuzzy == 1

    async def test_same_title_different_budget_is_new(
        self, session: AsyncSession
    ) -> None:
        """Similar text but a very different budget → separate order."""
        collector = Collector()
        await collector.collect(session, [listing("f-1", budget_min=20000)])
        await session.commit()
        result = await collector.collect(
            session, [listing("f-2", budget_min=80000)]
        )
        assert len(result.new_projects) == 1
