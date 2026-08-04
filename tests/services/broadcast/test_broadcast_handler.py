"""Проверки админского FSM рассылки без обращений к Telegram API."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ConversationHandler

from bot.handlers import broadcast_handler as handler
from services.broadcast.owner_groups import OwnerGroup
from services.broadcast.repository import GroupRecord


def _message(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "text": "",
        "chat_id": 100,
        "message_id": 200,
        "media_group_id": None,
        "reply_text": AsyncMock(return_value=SimpleNamespace(message_id=201)),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _query(data: str, message: SimpleNamespace | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        message=message or _message(),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


def _context(**user_data: object) -> SimpleNamespace:
    application = SimpleNamespace(bot_data={}, create_task=MagicMock())
    return SimpleNamespace(user_data=dict(user_data), application=application, bot=None)


def _update(
    *,
    message: SimpleNamespace | None = None,
    query: SimpleNamespace | None = None,
) -> SimpleNamespace:
    effective_message = message or (query.message if query else None)
    return SimpleNamespace(
        message=message,
        callback_query=query,
        effective_message=effective_message,
    )


def _repository() -> MagicMock:
    repository = MagicMock()
    for method in (
        "create_group",
        "list_groups",
        "get_group",
        "delete_group",
        "add_recipient",
        "list_recipients",
        "count_recipients",
        "create_broadcast",
        "set_progress_message",
        "history",
        "set_status",
    ):
        setattr(repository, method, AsyncMock())
    return repository


@pytest.fixture
def group() -> GroupRecord:
    return GroupRecord(7, handler.OWNER_CHAT_ID, "Клиенты", datetime(2026, 1, 1))


@pytest.mark.asyncio
async def test_group_creation_and_authorized_chat_flow(monkeypatch, group) -> None:
    repository = _repository()
    repository.create_group.return_value = group.id
    repository.add_recipient.return_value = True
    repository.list_recipients.return_value = [object()]
    monkeypatch.setattr(handler, "_repository", lambda: repository)

    context = _context()
    invalid = _message(text=" " * 3)
    assert (
        await handler.save_group_name.__wrapped__(_update(message=invalid), context)
        == handler.ENTERING_GROUP_NAME
    )

    named = _message(text="  Клиенты  ")
    assert (
        await handler.save_group_name.__wrapped__(_update(message=named), context)
        == handler.ADDING_CHAT
    )
    assert context.user_data["current_group_id"] == group.id

    monkeypatch.setattr(
        handler,
        "_resolve_authorized_chat",
        AsyncMock(
            return_value={
                "chat_id": -1001,
                "chat_type": "channel",
                "title": "Новости",
                "username": "news_feed",
                "language_code": "ru",
            }
        ),
    )
    chat_message = _message(text="@news_feed")
    assert (
        await handler.add_chat.__wrapped__(_update(message=chat_message), context)
        == handler.ADDING_CHAT
    )
    repository.add_recipient.assert_awaited_once()

    done_message = _message(text="/done")
    assert (
        await handler.done_adding.__wrapped__(_update(message=done_message), context)
        == ConversationHandler.END
    )
    assert "current_group_id" not in context.user_data


@pytest.mark.asyncio
async def test_chat_permission_resolution_rejects_unsafe_targets() -> None:
    context = _context()
    bot = SimpleNamespace(id=99, get_chat=AsyncMock(), get_chat_member=AsyncMock())
    context.bot = bot

    assert await handler._resolve_authorized_chat("bad link", context) is None

    bot.get_chat.return_value = SimpleNamespace(
        id=-1001,
        type="channel",
        title="Новости",
        full_name=None,
        username="news_feed",
    )
    bot.get_chat_member.return_value = SimpleNamespace(
        status="administrator",
        user=SimpleNamespace(language_code="ru"),
    )
    resolved = await handler._resolve_authorized_chat("https://t.me/news_feed", context)
    assert resolved == {
        "chat_id": -1001,
        "chat_type": "channel",
        "title": "Новости",
        "username": "news_feed",
        "language_code": "ru",
    }

    bot.get_chat_member.return_value.status = "left"
    assert await handler._resolve_authorized_chat("@news_feed", context) is None


@pytest.mark.asyncio
async def test_audience_filters_and_message_preview(monkeypatch, group) -> None:
    repository = _repository()
    repository.list_groups.return_value = [group]
    repository.get_group.return_value = group
    repository.count_recipients.return_value = 3
    monkeypatch.setattr(handler, "_repository", lambda: repository)
    context = _context()

    start_query = _query("bcast_send_start")
    assert (
        await handler.send_start.__wrapped__(_update(query=start_query), context)
        == handler.SELECTING_GROUP
    )

    select_query = _query(f"bcast_select_group_{group.id}")
    assert (
        await handler.group_selected.__wrapped__(_update(query=select_query), context)
        == handler.SELECTING_FILTERS
    )
    assert context.user_data["broadcast_group_id"] == group.id

    filter_query = _query("bcast_filter_type_group")
    assert (
        await handler.change_filters.__wrapped__(_update(query=filter_query), context)
        == handler.SELECTING_FILTERS
    )
    assert context.user_data["broadcast_filters"]["chat_types"] == [
        "group",
        "supergroup",
    ]

    done_query = _query("bcast_filter_done")
    assert (
        await handler.change_filters.__wrapped__(_update(query=done_query), context)
        == handler.ENTERING_MESSAGE
    )

    source = _message(message_id=301)
    assert (
        await handler.receive_message.__wrapped__(_update(message=source), context)
        == handler.CHOOSING_BUTTONS
    )
    skip_query = _query("bcast_buttons_skip", source)
    assert (
        await handler.choose_buttons.__wrapped__(_update(query=skip_query), context)
        == handler.CONFIRMING
    )
    source.reply_text.assert_awaited()


@pytest.mark.asyncio
async def test_album_buttons_enqueue_and_controls(monkeypatch, group) -> None:
    repository = _repository()
    repository.count_recipients.return_value = 2
    repository.create_broadcast.return_value = (42, 2)
    repository.set_status.return_value = True
    monkeypatch.setattr(handler, "_repository", lambda: repository)
    context = _context(
        broadcast_group_id=group.id,
        broadcast_filters={"chat_types": [], "languages": []},
    )

    first = _message(message_id=10, media_group_id="album")
    assert (
        await handler.receive_message.__wrapped__(_update(message=first), context)
        == handler.COLLECTING_ALBUM
    )
    second = _message(message_id=11, media_group_id="album")
    await handler.collect_album.__wrapped__(_update(message=second), context)
    finish = _message(text="/done")
    assert (
        await handler.finish_album.__wrapped__(_update(message=finish), context)
        == handler.CHOOSING_BUTTONS
    )

    buttons_message = _message(text="Сайт | https://example.com")
    assert (
        await handler.receive_buttons.__wrapped__(
            _update(message=buttons_message), context
        )
        == handler.CONFIRMING
    )
    assert context.user_data["broadcast_reply_markup"][0][0]["url"].startswith(
        "https://"
    )

    query = _query("bcast_confirm_now", _message(chat_id=500, message_id=600))
    assert (
        await handler.confirm_broadcast.__wrapped__(_update(query=query), context)
        == ConversationHandler.END
    )
    repository.create_broadcast.assert_awaited_once()
    assert "broadcast_group_id" not in context.user_data

    runner = SimpleNamespace(run_due=MagicMock(return_value=None))
    context.application.bot_data["broadcast_runner"] = runner
    control_query = _query("bcast_pause_42")
    await handler.control_broadcast.__wrapped__(_update(query=control_query), context)
    repository.set_status.assert_awaited_with(42, "paused")
    context.application.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_cancel_timeout_and_registration(monkeypatch) -> None:
    context = _context(
        broadcast_group_id=1,
        broadcast_source_chat_id=2,
        broadcast_source_message_ids=[3],
    )
    invalid = _message(text="не дата")
    assert (
        await handler.receive_schedule.__wrapped__(_update(message=invalid), context)
        == handler.ENTERING_SCHEDULE
    )

    cancel_message = _message()
    assert (
        await handler.cancel(_update(message=cancel_message), context)
        == ConversationHandler.END
    )
    assert not context.user_data

    context.user_data["broadcast_group_id"] = 1
    timeout_message = _message()
    assert (
        await handler.conversation_timeout(_update(message=timeout_message), context)
        == ConversationHandler.END
    )
    assert not context.user_data
    assert handler.get_broadcast_handler().persistent is True
    assert len(handler.get_broadcast_handlers()) == 6


@pytest.mark.asyncio
async def test_my_groups_start_shows_picker(monkeypatch, group) -> None:
    repository = _repository()
    monkeypatch.setattr(handler, "_repository", lambda: repository)
    monkeypatch.setattr(
        handler,
        "_list_owner_groups",
        AsyncMock(
            return_value=[
                OwnerGroup(-1001, "channel", "Новости", "news"),
                OwnerGroup(-1002, "supergroup", "Команда", None),
            ]
        ),
    )
    context = _context(current_group_id=group.id)
    query = _query("bcast_my_groups")

    assert (
        await handler.my_groups_start.__wrapped__(_update(query=query), context)
        == handler.ADDING_CHAT
    )
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert "bcast_my_group_pick_-1001" in callbacks
    assert "bcast_my_group_pick_-1002" in callbacks


@pytest.mark.asyncio
async def test_my_groups_start_falls_back_to_manual_entry(monkeypatch, group) -> None:
    repository = _repository()
    monkeypatch.setattr(handler, "_repository", lambda: repository)
    monkeypatch.setattr(handler, "_list_owner_groups", AsyncMock(return_value=None))
    context = _context(current_group_id=group.id)
    query = _query("bcast_my_groups")

    assert (
        await handler.my_groups_start.__wrapped__(_update(query=query), context)
        == handler.ADDING_CHAT
    )
    text = query.edit_message_text.await_args.args[0]
    assert "вручную" in text


@pytest.mark.asyncio
async def test_my_group_picked_adds_validated_chat(monkeypatch, group) -> None:
    repository = _repository()
    repository.add_recipient.return_value = True
    monkeypatch.setattr(handler, "_repository", lambda: repository)
    monkeypatch.setattr(
        handler,
        "_resolve_authorized_chat",
        AsyncMock(
            return_value={
                "chat_id": -1001,
                "chat_type": "channel",
                "title": "Новости",
                "username": "news",
                "language_code": "ru",
            }
        ),
    )
    context = _context(current_group_id=group.id)
    query = _query("bcast_my_group_pick_-1001")

    assert (
        await handler.my_group_picked.__wrapped__(_update(query=query), context)
        == handler.ADDING_CHAT
    )
    repository.add_recipient.assert_awaited_once()
    assert repository.add_recipient.await_args.kwargs["chat_id"] == -1001
    assert "добавлен" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_my_group_picked_rejects_without_permission(monkeypatch, group) -> None:
    repository = _repository()
    monkeypatch.setattr(handler, "_repository", lambda: repository)
    monkeypatch.setattr(
        handler, "_resolve_authorized_chat", AsyncMock(return_value=None)
    )
    context = _context(current_group_id=group.id)
    query = _query("bcast_my_group_pick_-1001")

    assert (
        await handler.my_group_picked.__wrapped__(_update(query=query), context)
        == handler.ADDING_CHAT
    )
    repository.add_recipient.assert_not_awaited()
    assert "не может публиковать" in query.edit_message_text.await_args.args[0]
