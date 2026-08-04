"""Юнит-тесты списка собственных групп владельца (Telethon мокается)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.broadcast import owner_groups
from services.broadcast.owner_groups import OwnerGroup


def _entity(kind: str, **attrs: object) -> object:
    """Создать объект с именем класса, как у TL-сущностей Telethon."""
    return type(kind, (object,), attrs)()


def _dialog(entity: object, name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(entity=entity, name=name)


class TestMapDialog:
    def test_maps_channel(self) -> None:
        entity = _entity("Channel", id=-1001, broadcast=True, username="news")
        assert owner_groups._map_dialog(_dialog(entity, "Новости")) == OwnerGroup(
            chat_id=-1001,
            chat_type="channel",
            title="Новости",
            username="news",
        )

    def test_maps_supergroup_channel(self) -> None:
        entity = _entity("Channel", id=-1002, broadcast=False, username=None)
        mapped = owner_groups._map_dialog(_dialog(entity, "Команда"))
        assert mapped is not None
        assert mapped.chat_type == "supergroup"

    def test_maps_legacy_group(self) -> None:
        entity = _entity("Chat", id=-1003, title="Старая группа")
        mapped = owner_groups._map_dialog(_dialog(entity, None))
        assert mapped is not None
        assert mapped.chat_type == "supergroup"
        assert mapped.title == "Старая группа"

    def test_skips_private_user(self) -> None:
        entity = _entity("User", id=42, first_name="Иван")
        assert owner_groups._map_dialog(_dialog(entity, "Иван")) is None

    def test_skips_missing_chat_id(self) -> None:
        entity = _entity("Channel", broadcast=True)
        assert owner_groups._map_dialog(_dialog(entity, "Без id")) is None


class FakeClient:
    """Клиент, отдающий заранее заданные диалоги; ``connect``/``disconnect`` пустые."""

    def __init__(self, dialogs: list[SimpleNamespace]) -> None:
        self._dialogs = iter(dialogs)
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()

    async def iter_dialogs(self):
        for dialog in self._dialogs:
            yield dialog


@pytest.mark.asyncio
async def test_list_owner_groups_with_injected_client(monkeypatch) -> None:
    monkeypatch.setattr(owner_groups, "_session_configured", lambda: True)
    channel = _entity("Channel", id=-1001, broadcast=True, username="news")
    user = _entity("User", id=42)
    client = FakeClient([_dialog(channel, "Новости"), _dialog(user, "Иван")])
    groups = await owner_groups.list_owner_groups(client=client)
    assert groups == [
        OwnerGroup(chat_id=-1001, chat_type="channel", title="Новости", username="news")
    ]
    client.connect.assert_not_called()
    client.disconnect.assert_not_called()


@pytest.mark.asyncio
async def test_list_owner_groups_returns_none_without_session(monkeypatch) -> None:
    monkeypatch.setattr(owner_groups, "_session_configured", lambda: False)
    assert await owner_groups.list_owner_groups(client=FakeClient([])) is None


@pytest.mark.asyncio
async def test_list_owner_groups_creates_and_closes_real_client(monkeypatch) -> None:
    """Продакшн-путь: создаётся свой клиент, подключается и корректно закрывается."""
    import telethon

    monkeypatch.setattr(owner_groups, "_session_configured", lambda: True)
    channel = _entity("Channel", id=-1001, broadcast=True, username="news")
    fake = FakeClient([_dialog(channel, "Новости")])
    monkeypatch.setattr(telethon, "TelegramClient", lambda *_a, **_k: fake)

    groups = await owner_groups.list_owner_groups()

    assert groups == [OwnerGroup(-1001, "channel", "Новости", "news")]
    fake.connect.assert_awaited_once()
    fake.disconnect.assert_awaited_once()
