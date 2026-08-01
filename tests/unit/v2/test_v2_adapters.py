"""Adapter tests — §3.1: единый интерфейс fetch() -> list[RawListing]."""

from typing import List

import httpx

from core.models import Platform
from db.models import JobVacancy
from monitoring.adapters.base import RawListing, SourceAdapter
from monitoring.adapters.fl_ru import FLRuAdapter, parse_budget, parse_projects_html
from monitoring.adapters.kwork import KworkAdapter, vacancy_to_listing
from monitoring.adapters.telegram_channels import TelegramChannelsAdapter


def _vacancy(kwork_id: str = "k-1") -> JobVacancy:
    return JobVacancy(
        kwork_id=kwork_id,
        url=f"https://kwork.ru/projects/{kwork_id}",
        title="Нужен бот",
        description="Описание задачи",
        budget="до 30 000 ₽",
        budget_min=20000,
        budget_max=30000,
        category="Боты",
        proposals_count=3,
        customer_rating=4.9,
        customer_orders=15,
    )


class FakeKworkParser:
    def __init__(self) -> None:
        self.cleaned = False

    async def fetch_vacancies(self, limit: int = 10) -> List[JobVacancy]:
        return [_vacancy("k-1"), _vacancy("k-2")]

    async def cleanup(self) -> None:
        self.cleaned = True


class FakeTgParser:
    def __init__(self) -> None:
        self.disconnected = False

    async def fetch_messages_from_channel(
        self, channel: str, limit: int = 20
    ) -> List[JobVacancy]:
        if channel == "@empty":
            return []
        return [_vacancy(f"{channel}-msg1")]

    async def disconnect(self) -> None:
        self.disconnected = True


class TestKworkAdapter:
    def test_mapping_preserves_scoring_signals(self) -> None:
        """client rating/orders/proposals feed §3.3 features."""
        listing = vacancy_to_listing(_vacancy(), Platform.KWORK)
        assert listing.source is Platform.KWORK
        assert listing.external_id == "k-1"
        assert listing.budget_min == 20000
        assert listing.client_rating == 4.9
        assert listing.client_orders == 15
        assert listing.proposals_count == 3

    async def test_fetch_returns_listings(self) -> None:
        """Adapter conforms to the §3.1 interface."""
        adapter = KworkAdapter(parser=FakeKworkParser())
        assert isinstance(adapter, SourceAdapter)
        listings = await adapter.fetch()
        assert len(listings) == 2
        assert all(isinstance(item, RawListing) for item in listings)

    async def test_close_releases_parser_browser(self) -> None:
        parser = FakeKworkParser()
        adapter = KworkAdapter(parser=parser)
        await adapter.close()
        assert parser.cleaned is True


class TestTelegramAdapter:
    async def test_fetch_tags_channel(self) -> None:
        """Each listing carries its channel for connection matching."""
        adapter = TelegramChannelsAdapter(
            ["orders_channel", "@empty"], parser=FakeTgParser()
        )
        listings = await adapter.fetch()
        assert len(listings) == 1
        assert listings[0].raw_payload["channel"] == "@orders_channel"
        assert listings[0].source is Platform.TG_CHANNEL

    async def test_no_channels_no_fetch(self) -> None:
        """Empty channel list is a no-op."""
        adapter = TelegramChannelsAdapter([], parser=FakeTgParser())
        assert await adapter.fetch() == []

    async def test_close_disconnects_parser(self) -> None:
        """Adapter releases parser resources."""
        parser = FakeTgParser()
        adapter = TelegramChannelsAdapter(["@a"], parser=parser)
        await adapter.close()
        assert parser.disconnected is True


FL_RU_HTML = """
<html><body>
  <div class="project">
    <a href="/projects/5001234/">Разработка Telegram-бота для магазина</a>
    <span>Бюджет: 25 000 руб</span>
  </div>
  <div class="project">
    <a href="/projects/5001235/">Парсинг сайтов недвижимости</a>
    <span>По договорённости</span>
  </div>
  <a href="/projects/5001234/">Разработка Telegram-бота для магазина</a>
  <a href="/projects/">Все проекты</a>
</body></html>
"""


class TestFLRuAdapter:
    def test_parse_budget(self) -> None:
        """Ruble amounts with spaces are parsed."""
        assert parse_budget("Бюджет: 25 000 руб") == 25000
        assert parse_budget("По договорённости") is None

    def test_parse_projects_html(self) -> None:
        """Cards are extracted, duplicates and nav links skipped."""
        listings = parse_projects_html(FL_RU_HTML)
        assert len(listings) == 2
        first = listings[0]
        assert first.source is Platform.FL_RU
        assert first.external_id == "5001234"
        assert first.budget_min == 25000
        assert first.url == "https://www.fl.ru/projects/5001234/"

    async def test_fetch_with_mock_transport(self) -> None:
        """Full fetch through httpx MockTransport (no network, §11)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=FL_RU_HTML)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = FLRuAdapter(client=client, delay_range=(0.0, 0.0))
        listings = await adapter.fetch()
        assert len(listings) == 2
        await adapter.close()

    async def test_fetch_http_error_returns_empty(self) -> None:
        """A broken source never raises into the tick (§3.1)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = FLRuAdapter(client=client, delay_range=(0.0, 0.0))
        assert await adapter.fetch() == []
        await adapter.close()


class FailingTgParser:
    async def fetch_messages_from_channel(
        self, channel: str, limit: int = 20
    ) -> List[JobVacancy]:
        if channel == "@broken":
            raise ConnectionError("flood wait")
        return [_vacancy(f"{channel}-ok")]


class TestTelegramAdapterErrors:
    async def test_broken_channel_isolated(self) -> None:
        """One failing channel doesn't kill the rest (§3.1)."""
        adapter = TelegramChannelsAdapter(
            ["@broken", "@alive"], parser=FailingTgParser()
        )
        listings = await adapter.fetch()
        assert len(listings) == 1
        assert listings[0].raw_payload["channel"] == "@alive"

    async def test_close_without_parser_is_noop(self) -> None:
        """close() before any fetch is safe."""
        adapter = TelegramChannelsAdapter(["@a"])
        await adapter.close()
