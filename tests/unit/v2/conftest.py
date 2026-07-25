"""Shared fixtures for V2 tests: in-memory DB, fake LLM, fake Telegram objects."""
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import AsyncIterator, List, Optional
from unittest.mock import AsyncMock

# Config must be importable before app modules (matches CI env).
os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("OWNER_CHAT_ID", "123456789")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "test_hash")

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from core import db as core_db
from core.llm import OpenRouterClient
from core.models import (
    Base,
    ExchangeConnection,
    Platform,
    PortfolioItem,
    Project,
    SubscriptionTier,
    User,
    utcnow,
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """In-memory SQLite engine with the full V2 schema."""
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory bound to the test engine, installed globally."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    core_db.set_session_factory(factory)
    yield factory
    core_db.set_session_factory(None)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One open session per test."""
    async with session_factory() as sess:
        yield sess


@pytest.fixture
async def user(session: AsyncSession) -> User:
    """A trial user with a configured profile."""
    row = User(
        telegram_id=555001,
        username="freelancer",
        target_hourly_rate=1500,
        tax_rate=0.06,
        skills=["python", "telegram-боты", "парсинг"],
        subscription_tier=SubscriptionTier.TRIAL,
        subscription_expires_at=utcnow() + timedelta(days=7),
    )
    session.add(row)
    await session.commit()
    return row


@pytest.fixture
async def portfolio(session: AsyncSession, user: User) -> List[PortfolioItem]:
    """Two portfolio cases for the user."""
    items = [
        PortfolioItem(
            user_id=user.id,
            title="Бот записи для барбершопа",
            description="Telegram-бот на python-telegram-bot: запись, напоминания, "
            "оплата. Клиент сократил ручную запись на 80%. Опыт 5 лет.",
            tags=["python", "telegram-боты"],
        ),
        PortfolioItem(
            user_id=user.id,
            title="Парсер маркетплейсов",
            description="Playwright-парсер цен конкурентов с отчётами в Google Sheets.",
            tags=["парсинг", "playwright"],
        ),
    ]
    session.add_all(items)
    await session.commit()
    return items


def make_project(
    external_id: str = "kw-1",
    source: Platform = Platform.KWORK,
    title: str = "Нужен Telegram-бот для записи клиентов",
    budget_min: Optional[int] = 20000,
    budget_max: Optional[int] = 30000,
    posted_at: Optional[datetime] = None,
    **kwargs: object,
) -> Project:
    """Build an unsaved Project row with sensible defaults."""
    return Project(
        source=source,
        external_id=external_id,
        title=title,
        description_raw="Нужен бот: запись, оплата, напоминания. Срок 2 недели.",
        budget_min=budget_min,
        budget_max=budget_max,
        posted_at=posted_at or utcnow(),
        proposals_count=4,
        client_rating=4.7,
        client_orders=12,
        category="Telegram-бот",
        url="https://kwork.ru/projects/1",
        **kwargs,
    )


@pytest.fixture
async def project(session: AsyncSession) -> Project:
    """A saved sample project."""
    row = make_project()
    session.add(row)
    await session.commit()
    return row


@pytest.fixture
async def kwork_connection(
    session: AsyncSession, user: User
) -> ExchangeConnection:
    """An active Kwork connection for the user."""
    row = ExchangeConnection(user_id=user.id, platform=Platform.KWORK)
    session.add(row)
    await session.commit()
    return row


class FakeLLM(OpenRouterClient):
    """Scripted LLM double: returns queued responses, records calls."""

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        super().__init__(api_key="fake")
        self.responses = list(responses or [])
        self.calls: List[dict] = []

    async def chat(
        self,
        messages: List[dict],
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 800,
        json_mode: bool = False,
    ) -> str:
        self.calls.append(
            {"messages": messages, "model": model, "json_mode": json_mode}
        )
        if not self.responses:
            raise AssertionError("FakeLLM: no scripted responses left")
        return self.responses.pop(0)


GOOD_PROPOSAL = (
    "Задача с записью клиентов для барбершопа мне хорошо знакома: делал бота "
    "записи на python-telegram-bot — с напоминаниями и приёмом оплат, ручная "
    "запись у клиента сократилась на 80%. Для вашего салона предлагаю тот же "
    "проверенный каркас: онлайн-запись через меню, автоматические напоминания "
    "клиентам, приём предоплаты и админ-панель для мастеров. По описанию вижу, "
    "что вам важны запись, оплата и напоминания — все три блока уже "
    "реализованы в моём кейсе, поэтому рисков со сроками не вижу и могу "
    "приступить сразу после уточнения деталей. Сориентируйте, пожалуйста, по "
    "количеству мастеров и филиалов — от этого зависит структура расписания. "
    "Удобно будет созвониться на десять минут завтра, чтобы обсудить детали?"
)


@pytest.fixture
def fake_llm() -> FakeLLM:
    """A FakeLLM preloaded with one clean proposal."""
    return FakeLLM([GOOD_PROPOSAL])


class FakeMessage:
    """Message double with awaitable reply methods."""

    def __init__(self, text: Optional[str] = None) -> None:
        self.text = text
        self.reply_text = AsyncMock()
        self.delete = AsyncMock()


class FakeCallbackQuery:
    """Callback-query double."""

    def __init__(self, data: str, message: Optional[FakeMessage] = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()


def make_update(
    telegram_id: int = 555001,
    text: Optional[str] = None,
    callback_data: Optional[str] = None,
    username: str = "freelancer",
) -> SimpleNamespace:
    """Build a fake Update for handler tests."""
    effective_user = SimpleNamespace(id=telegram_id, username=username)
    message = FakeMessage(text)
    callback_query = (
        FakeCallbackQuery(callback_data) if callback_data is not None else None
    )
    return SimpleNamespace(
        effective_user=effective_user,
        message=message if callback_data is None else None,
        callback_query=callback_query,
    )


def make_context(
    args: Optional[List[str]] = None,
) -> SimpleNamespace:
    """Build a fake handler context."""
    return SimpleNamespace(user_data={}, args=args or [])
