"""Список собственных групп/каналов владельца для безопасной рассылки.

Чтение наружу собственных диалогов делается ТОЛЬКО через отдельную
Telethon-сессию (AGENTS.md §8: выделенный аккаунт, только чтение, никаких
рассылок от его имени). Если Telethon-сессия не настроена или не импортируется
— возвращается ``None``, и владелец добавляет чаты вручную существующим
потоком (chat_id / @username / ссылка) с обязательной проверкой права
публикации бота.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config import get_config


@dataclass(frozen=True)
class OwnerGroup:
    """Один собственный чат владельца (группа/канал), куда можно публиковать."""

    chat_id: int
    chat_type: str
    title: str
    username: Optional[str]


def _session_configured() -> bool:
    config = get_config()
    return bool(
        config.TELETHON_API_ID
        and config.TELETHON_API_HASH
        and config.TELETHON_SESSION_NAME
    )


def _entity_chat_type(entity: Any) -> Optional[str]:
    """Определить тип чата по TL-классу сущности (или ``None`` для личного чата)."""
    kind = type(entity).__name__
    if kind == "Channel":
        # Каналы: broadcast=True; супергруппы тоже живут в Channel (megagroup).
        return "channel" if bool(getattr(entity, "broadcast", False)) else "supergroup"
    if kind in ("Chat", "ChatForbidden"):
        return "supergroup"
    # User / ChatEmpty / service-сущности — это не «мои группы».
    return None


def _map_dialog(dialog: Any) -> Optional[OwnerGroup]:
    """Смапить dialog-объект Telethon в :class:`OwnerGroup` либо вернуть ``None``."""
    entity = getattr(dialog, "entity", None)
    chat_id = int(getattr(entity, "id", 0) or 0)
    if not chat_id:
        return None
    chat_type = _entity_chat_type(entity)
    if chat_type is None:
        return None
    title = str(getattr(dialog, "name", "") or "")
    if not title:
        title = str(getattr(entity, "title", "") or "")
    username = getattr(entity, "username", None)
    return OwnerGroup(
        chat_id=chat_id, chat_type=chat_type, title=title, username=username
    )


async def list_owner_groups(
    client: Optional[Any] = None,
) -> Optional[list[OwnerGroup]]:
    """Вернуть собственные чаты владельца или ``None`` при отсутствии сессии.

    ``client`` даёт возможность внедрить фейковый/моковый ``TelegramClient``
    в unit-тестах; по умолчанию создаётся и корректно закрывается реальный
    клиент из настроек выделенного аккаунта.
    """
    if not _session_configured():
        return None
    owns_client = client is None
    if owns_client:
        try:
            from telethon import TelegramClient
        except ImportError:
            return None
        config = get_config()
        client = TelegramClient(
            config.TELETHON_SESSION_NAME,
            config.TELETHON_API_ID,
            config.TELETHON_API_HASH,
        )
    try:
        if owns_client and client is not None:
            await client.connect()
        groups: list[OwnerGroup] = []
        async for dialog in client.iter_dialogs():
            mapped = _map_dialog(dialog)
            if mapped is not None:
                groups.append(mapped)
        return groups
    finally:
        if owns_client and client is not None:
            await client.disconnect()
