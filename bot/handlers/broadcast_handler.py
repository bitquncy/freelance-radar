"""Админский UX безопасной рассылки по разрешённым чатам."""

from __future__ import annotations

import aiosqlite
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

import telegram

from services.logger_config import get_logger
from services.broadcast.repository import BroadcastRepository
from bot.auth import owner_only
from db import queries
from config import BROADCAST_TIMEZONE, DB_PATH, OWNER_CHAT_ID
from emoji_config import (
    P,
    danger_button,
    inline_button,
    neutral_button,
    primary_button,
    success_button,
)

logger = get_logger(__name__)

# Conversation states
(
    ENTERING_GROUP_NAME,
    SELECTING_GROUP_FOR_BROADCAST,
    ENTERING_BROADCAST_MESSAGE,
    CONFIRMING_BROADCAST,
    ADDING_CHAT_ID,
    ENTERING_SCHEDULE,
) = range(6)


# ─── Main menu ───────────────────────────────────────────────────────


@owner_only
async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show broadcast main menu."""
    await update.message.reply_text(
        f"{P.MEGAPHONE} **Рассылка сообщений**\n\n"
        "Только чаты, где бот уже имеет право публиковать. "
        "Автопоиск и вступление в чужие группы отключены.\n\n"
        "Выберите действие:",
        reply_markup=_main_keyboard(),
        parse_mode=None,
    )


def _main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            success_button(
                "Создать группу чатов", icon=P.PLUS, callback_data="bcast_group_create"
            )
        ],
        [primary_button("Мои группы", icon=P.LIST, callback_data="bcast_group_list")],
        [
            success_button(
                "Новая рассылка", icon=P.INBOX, callback_data="bcast_send_start"
            )
        ],
        [
            primary_button(
                "История рассылок", icon=P.SCROLL, callback_data="bcast_history"
            )
        ],
        [neutral_button("Назад", icon=P.PREV, callback_data="back_to_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ─── Group CRUD ──────────────────────────────────────────────────────


@owner_only
async def create_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start creating a new chat group."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        f"{P.PLUS} **Новая группа чатов**\n\n"
        'Введите название группы (например: "Дизайн-каналы"):\n\n'
        "/cancel — отмена",
        reply_markup=_cancel_kb(),
        parse_mode=None,
    )
    return ENTERING_GROUP_NAME


@owner_only
async def save_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save group name."""
    name = update.message.text.strip()

    if len(name) > 100:
        await update.message.reply_text(
            f"{P.CROSS} Название слишком длинное (макс 100 символов)."
        )
        return ENTERING_GROUP_NAME

    async with aiosqlite.connect(DB_PATH) as db:
        group_id = await queries.create_chat_group(db, OWNER_CHAT_ID, name)

    await update.message.reply_text(
        f"{P.CHECK} Группа «{name}» создана (ID: {group_id})\n\n"
        "Теперь добавьте чаты в группу. Отправьте:\n"
        "• Chat ID (например: `-1002006920508`)\n"
        "• @username канала (например: `@freelance_chat`)\n"
        "• URL канала (например: `https://t.me/freelance_chat`)\n\n"
        "/done — завершить добавление\n"
        "/cancel — отмена",
        reply_markup=_cancel_kb(),
    )
    context.user_data["current_group_id"] = group_id
    return ADDING_CHAT_ID


@owner_only
async def add_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Add a chat ID to the current group."""
    chat_id = update.message.text.strip()
    group_id = context.user_data.get("current_group_id")

    if not group_id:
        await update.message.reply_text(f"{P.CROSS} Группа не найдена. Начните заново.")
        return ConversationHandler.END

    # Разрешаем только чаты, в которых Telegram подтверждает право бота писать.
    resolved = await _resolve_authorized_chat(chat_id, context)

    if not resolved:
        await update.message.reply_text(
            f"{P.CROSS} Не удалось подтвердить право публикации в `{chat_id}`.\n"
            "Сначала добавьте бота в чат. Для канала выдайте ему права администратора, "
            "для группы — право отправлять сообщения.\n"
            "Или /done для завершения.",
            parse_mode=None,
        )
        return ADDING_CHAT_ID
    resolved_id, resolved_title = resolved

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await queries.add_chat_to_group(db, group_id, resolved_id, resolved_title)
            await update.message.reply_text(
                f"{P.CHECK} Чат `{resolved_id}` (original: {chat_id}) добавлен в группу.\n"
                "Отправьте следующий ID или /done.",
                parse_mode=None,
            )
        except (aiosqlite.Error, ValueError, TypeError, KeyError) as e:
            await update.message.reply_text(
                f"{P.CROSS} Ошибка: {e}\nПопробуйте другой ID или /done."
            )

    return ADDING_CHAT_ID


async def _resolve_authorized_chat(text: str, context) -> tuple[str, str] | None:
    """Разрешить идентификатор и подтвердить право бота публиковать."""
    import re

    text = text.strip()

    candidate = text
    url_match = re.match(r"https?://t\.me/([^/]+)", text)
    if url_match:
        username = url_match.group(1)
        candidate = username if username.startswith("@") else f"@{username}"
    elif not re.match(r"^-?\d+$", text) and not text.startswith("@"):
        return None

    try:
        chat = await context.bot.get_chat(candidate)
        membership = await context.bot.get_chat_member(chat.id, context.bot.id)
    except (telegram.error.TelegramError, ValueError, TypeError) as exc:
        logger.warning("broadcast.resolve_failed", reference=text, error=str(exc))
        return None

    status = str(membership.status)
    if status in {"left", "kicked"}:
        return None
    if str(chat.type) == "channel" and status not in {
        "administrator",
        "creator",
        "owner",
    }:
        return None
    if status == "restricted" and not bool(
        getattr(membership, "can_send_messages", False)
    ):
        return None
    title = chat.title or chat.full_name or chat.username or str(chat.id)
    return str(chat.id), str(title)


@owner_only
async def add_chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Добавить разрешённый чат в существующую группу."""
    query = update.callback_query
    await query.answer()
    group_id = int(query.data.replace("bcast_group_add_chat_", ""))
    context.user_data["current_group_id"] = group_id
    await query.edit_message_text(
        "Пришлите chat_id, @username или ссылку на чат.\n\n"
        "Бот уже должен состоять в нём и иметь право отправлять сообщения.\n"
        "/done — завершить · /cancel — отмена",
        reply_markup=_cancel_kb(),
    )
    return ADDING_CHAT_ID


@owner_only
async def done_adding_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finish adding chats to the group."""
    group_id = context.user_data.get("current_group_id")

    async with aiosqlite.connect(DB_PATH) as db:
        members = await queries.get_chat_group_members(db, group_id)

    await update.message.reply_text(
        f"{P.CHECK} Группа готова! Чатов: {len(members)}\n\n" "Выберите действие:",
        reply_markup=_main_keyboard(),
    )

    context.user_data.pop("current_group_id", None)
    return ConversationHandler.END


@owner_only
async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all chat groups."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        groups = await queries.get_chat_groups(db, OWNER_CHAT_ID)

    if not groups:
        await query.edit_message_text(
            f"{P.LIST} **Мои группы**\n\n" "Групп пока нет. Создайте первую!",
            reply_markup=_main_keyboard(),
            parse_mode=None,
        )
        return

    text = f"{P.LIST} **Мои группы чатов:**\n\n"
    keyboard = []
    for g in groups:
        # g is a tuple: (id, user_id, name, created_at)
        g_id = g[0]
        g_name = g[2]
        # Get member count
        async with aiosqlite.connect(DB_PATH) as db:
            members = await queries.get_chat_group_members(db, g_id)
        count = len(members)
        text += f"• **{g_name}** (ID: {g_id}) — {count} чатов\n"
        keyboard.append(
            [
                inline_button(
                    f"{g_name} ({count})",
                    icon=P.EYE,
                    callback_data=f"bcast_group_detail_{g_id}",
                ),
                danger_button(
                    "Удалить", icon=P.TRASH, callback_data=f"bcast_group_delete_{g_id}"
                ),
            ]
        )
    keyboard.append(
        [neutral_button("Назад", icon=P.PREV, callback_data="back_to_main")]
    )

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None
    )


@owner_only
async def group_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show group details."""
    query = update.callback_query
    await query.answer()

    group_id = int(query.data.replace("bcast_group_detail_", ""))

    async with aiosqlite.connect(DB_PATH) as db:
        members = await queries.get_chat_group_members(db, group_id)
        group = await queries.get_chat_group(db, group_id)

    if not group:
        await query.edit_message_text(f"{P.CROSS} Группа не найдена.")
        return

    # group is a tuple: (id, user_id, name, created_at)
    group_id = group[0]
    group_name = group[2]

    text = f"{P.EYE} **Группа: {group_name}**\n\n"
    text += f"ID: {group_id}\n"
    text += f"Чатов: {len(members)}\n\n"

    if members:
        text += "**Чаты:**\n"
        for m in members[:20]:
            # m is a tuple: (id, group_id, chat_id, chat_title, added_at)
            m_title = m[3] or m[2]
            text += f"  • {m_title}\n"
        if len(members) > 20:
            text += f"  ... и ещё {len(members) - 20}\n"

    keyboard = [
        [
            success_button(
                "Добавить чат",
                icon=P.PLUS,
                callback_data=f"bcast_group_add_chat_{group_id}",
            )
        ],
        [neutral_button("К списку", icon=P.PREV, callback_data="bcast_group_list")],
    ]

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None
    )


@owner_only
async def group_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a chat group."""
    query = update.callback_query
    await query.answer()

    group_id = int(query.data.replace("bcast_group_delete_", ""))

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.delete_chat_group(db, group_id)

    await query.edit_message_text(
        f"{P.CHECK} Группа удалена.", reply_markup=_main_keyboard()
    )


# ─── Sending ─────────────────────────────────────────────────────────


@owner_only
async def send_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start broadcast: select a group."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        groups = await queries.get_chat_groups(db, OWNER_CHAT_ID)

    if not groups:
        await query.edit_message_text(
            f"{P.CROSS} Нет групп для рассылки.\n" "Сначала создайте группу чатов.",
            reply_markup=_main_keyboard(),
        )
        return ConversationHandler.END

    text = f"{P.INBOX} **Выберите группу чатов для рассылки:**\n\n"
    keyboard = []
    for g in groups:
        # g is a tuple: (id, user_id, name, created_at)
        g_id = g[0]
        g_name = g[2]
        async with aiosqlite.connect(DB_PATH) as db:
            members = await queries.get_chat_group_members(db, g_id)
        keyboard.append(
            [
                inline_button(
                    f"{g_name} ({len(members)} чатов)",
                    icon=P.PEOPLE,
                    callback_data=f"bcast_select_group_{g_id}",
                )
            ]
        )
    keyboard.append(
        [neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_cancel")]
    )

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None
    )
    return SELECTING_GROUP_FOR_BROADCAST


@owner_only
async def group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Group selected, ask for message."""
    query = update.callback_query
    await query.answer()

    group_id = int(query.data.replace("bcast_select_group_", ""))
    context.user_data["broadcast_group_id"] = group_id

    async with aiosqlite.connect(DB_PATH) as db:
        group = await queries.get_chat_group(db, group_id)
        members = await queries.get_chat_group_members(db, group_id)

    # group is a tuple: (id, user_id, name, created_at)
    group_name = group[2] if group else "Unknown"
    await query.edit_message_text(
        f"{P.INBOX} **Группа: {group_name}** ({len(members)} чатов)\n\n"
        "Отправьте сообщение для рассылки.\n"
        "Поддерживается копирование текста, фото, видео, документа и других "
        "обычных сообщений без метки «переслано».\n\n"
        "/cancel — отмена",
        reply_markup=_cancel_kb(),
        parse_mode=None,
    )
    return ENTERING_BROADCAST_MESSAGE


@owner_only
async def receive_broadcast_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive broadcast message and show preview."""
    message = update.message
    context.user_data["broadcast_source_chat_id"] = message.chat_id
    context.user_data["broadcast_source_message_id"] = message.message_id

    text = f"{P.LIST} **Предпросмотр — сообщение выше**\n\n"
    if message.text:
        text += f"Тип: текст ({len(message.text)} символов)\n"
    elif message.photo:
        text += f"{P.CAMERA} Тип: фото\n"
    elif message.video:
        text += "🎬 Тип: видео\n"
    elif message.document:
        text += f"{P.DOC} Тип: документ\n"
    else:
        text += "Тип: копирование исходного сообщения\n"

    group_id = context.user_data.get("broadcast_group_id")

    async with aiosqlite.connect(DB_PATH) as db:
        group = await queries.get_chat_group(db, group_id)
        members = await queries.get_chat_group_members(db, group_id)

    # group is a tuple: (id, user_id, name, created_at)
    group_name = group[2] if group else "Unknown"
    text += f"\n{P.TARGET} Группа: {group_name} ({len(members)} чатов)\n"
    text += (
        "\nБудет использован безопасный Bot API. Получатели фиксируются при запуске, "
        "а повтор в один чат ограничен кулдауном."
    )

    await update.message.reply_text(
        text, reply_markup=_confirm_keyboard(), parse_mode=None
    )
    return CONFIRMING_BROADCAST


@owner_only
async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Поставить рассылку в очередь или перейти к выбору времени."""
    query = update.callback_query
    await query.answer()

    if query.data == "bcast_confirm_schedule":
        await query.edit_message_text(
            f"Введите дату и время запуска в часовом поясе {BROADCAST_TIMEZONE}.\n"
            "Формат: ДД.ММ.ГГГГ ЧЧ:ММ\n\n"
            "/cancel — отмена",
            reply_markup=_cancel_kb(),
        )
        return ENTERING_SCHEDULE
    if query.data == "bcast_confirm_now":
        return await _enqueue_broadcast(update, context, scheduled_at=None)
    if query.data in {"bcast_confirm_no", "bcast_cancel"}:
        await query.edit_message_text(
            f"{P.CROSS} Рассылка отменена.", reply_markup=_main_keyboard()
        )
        _clear_broadcast_draft(context)
        return ConversationHandler.END
    return CONFIRMING_BROADCAST


@owner_only
async def receive_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Разобрать локальное время отложенного запуска."""
    try:
        timezone_info = ZoneInfo(BROADCAST_TIMEZONE)
        local_value = datetime.strptime(update.message.text.strip(), "%d.%m.%Y %H:%M")
        scheduled_at = local_value.replace(tzinfo=timezone_info)
    except (ValueError, ZoneInfoNotFoundError):
        await update.message.reply_text(
            "Не удалось разобрать время. Используйте формат ДД.ММ.ГГГГ ЧЧ:ММ, "
            f"часовой пояс {BROADCAST_TIMEZONE}."
        )
        return ENTERING_SCHEDULE
    if scheduled_at <= datetime.now(timezone_info):
        await update.message.reply_text("Время запуска должно быть в будущем.")
        return ENTERING_SCHEDULE
    return await _enqueue_broadcast(update, context, scheduled_at=scheduled_at)


async def _enqueue_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    scheduled_at: datetime | None,
) -> int:
    """Создать снимок аудитории и передать кампанию фоновому воркеру."""
    group_id = context.user_data.get("broadcast_group_id")
    source_chat_id = context.user_data.get("broadcast_source_chat_id")
    source_message_id = context.user_data.get("broadcast_source_message_id")
    progress_message = (
        update.callback_query.message if update.callback_query else update.message
    )
    if not group_id or source_chat_id is None or source_message_id is None:
        await progress_message.reply_text(
            f"{P.CROSS} Черновик рассылки потерян. Начните заново."
        )
        _clear_broadcast_draft(context)
        return ConversationHandler.END

    repository = BroadcastRepository(DB_PATH)
    broadcast_id, total = await repository.create_broadcast(
        user_id=OWNER_CHAT_ID,
        group_id=int(group_id),
        source_chat_id=source_chat_id,
        source_message_id=int(source_message_id),
        progress_chat_id=progress_message.chat_id,
        progress_message_id=progress_message.message_id,
        scheduled_at=scheduled_at,
    )
    if scheduled_at:
        text = (
            f"🗓 Рассылка #{broadcast_id} запланирована на "
            f"{scheduled_at.strftime('%d.%m.%Y %H:%M')} ({BROADCAST_TIMEZONE}).\n"
            f"Получателей: {total}"
        )
    else:
        text = (
            f"📣 Рассылка #{broadcast_id} поставлена в очередь.\nПолучателей: {total}"
        )

    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)
        # Прогресс должен редактировать только что созданное сообщение, а не ввод времени.
        progress = await update.message.reply_text(
            f"⏳ Ожидание запуска рассылки #{broadcast_id}…"
        )
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE broadcasts SET progress_message_id = ? WHERE id = ?",
                (progress.message_id, broadcast_id),
            )
            await db.commit()

    runner = context.application.bot_data.get("broadcast_runner")
    if runner is not None and scheduled_at is None:
        context.application.create_task(runner.run_due())
    _clear_broadcast_draft(context)
    return ConversationHandler.END


# ─── History ─────────────────────────────────────────────────────────


@owner_only
async def broadcast_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show broadcast history."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        broadcasts = await queries.get_broadcast_history(db, OWNER_CHAT_ID)

    if not broadcasts:
        await query.edit_message_text(
            f"{P.SCROLL} **История рассылок**\n\n" "Рассылок пока нет.",
            reply_markup=_main_keyboard(),
            parse_mode=None,
        )
        return

    text = f"{P.SCROLL} **История рассылок:**\n\n"
    keyboard = []
    for b in broadcasts[:20]:
        # b is a tuple: (id, user_id, group_id, message_text, message_type, file_id, caption, sent_count, failed_count, status, created_at)
        b_status = b[9]
        b_created = b[10]
        b_sent = b[7]
        b_failed = b[8]
        status_emoji = (
            f"{P.CHECK}" if b_status in {"completed", "done"} else f"{P.HOURGLASS}"
        )
        text += f"{status_emoji} {str(b_created)[:16]} — {b_sent} отправлено, {b_failed} ошибок\n"
    text += f"\nВсего: {len(broadcasts)}"

    keyboard.append(
        [neutral_button("Назад", icon=P.PREV, callback_data="back_to_main")]
    )

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None
    )


# ─── Helpers ─────────────────────────────────────────────────────────


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    _clear_broadcast_draft(context)
    context.user_data.pop("current_group_id", None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            f"{P.CROSS} Операция отменена.", reply_markup=_main_keyboard()
        )
    else:
        await update.message.reply_text(
            f"{P.CROSS} Операция отменена.", reply_markup=_main_keyboard()
        )
    return ConversationHandler.END


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_cancel")]]
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                success_button(
                    "Отправить сейчас", icon=P.CHECK, callback_data="bcast_confirm_now"
                )
            ],
            [
                primary_button(
                    "Запланировать",
                    icon=P.TIMER,
                    callback_data="bcast_confirm_schedule",
                )
            ],
            [neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_confirm_no")],
        ]
    )


def _clear_broadcast_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удалить временные ссылки на исходное сообщение рассылки."""
    for key in (
        "broadcast_group_id",
        "broadcast_source_chat_id",
        "broadcast_source_message_id",
    ):
        context.user_data.pop(key, None)


@owner_only
async def control_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Поставить кампанию на паузу, продолжить или отменить."""
    query = update.callback_query
    action, raw_id = query.data.removeprefix("bcast_").split("_", maxsplit=1)
    broadcast_id = int(raw_id)
    target_status = {
        "pause": "paused",
        "resume": "queued",
        "stop": "cancelled",
    }[action]
    changed = await BroadcastRepository(DB_PATH).set_status(broadcast_id, target_status)
    if not changed:
        await query.answer(
            "Статус уже изменён или рассылка завершена.", show_alert=True
        )
        return
    labels = {
        "pause": "Рассылка поставлена на паузу.",
        "resume": "Рассылка продолжена.",
        "stop": "Рассылка остановлена.",
    }
    await query.answer(labels[action])
    runner = context.application.bot_data.get("broadcast_runner")
    if runner is not None:
        context.application.create_task(runner.run_due())


def get_broadcast_handler() -> ConversationHandler:
    """Get the broadcast conversation handler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("broadcast", broadcast_menu),
            CallbackQueryHandler(create_group_start, pattern="^bcast_group_create$"),
            CallbackQueryHandler(add_chat_start, pattern="^bcast_group_add_chat_"),
            CallbackQueryHandler(send_start, pattern="^bcast_send_start$"),
        ],
        states={
            ENTERING_GROUP_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_group_name)
            ],
            ADDING_CHAT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_chat_id),
                CommandHandler("done", done_adding_chats),
            ],
            SELECTING_GROUP_FOR_BROADCAST: [
                CallbackQueryHandler(group_selected, pattern="^bcast_select_group_")
            ],
            ENTERING_BROADCAST_MESSAGE: [
                MessageHandler(
                    filters.ALL & ~filters.COMMAND, receive_broadcast_message
                ),
            ],
            CONFIRMING_BROADCAST: [
                CallbackQueryHandler(confirm_broadcast, pattern="^bcast_confirm_")
            ],
            ENTERING_SCHEDULE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_schedule)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^bcast_cancel$"),
            CommandHandler("cancel", cancel),
        ],
        per_user=True,
        per_chat=True,
        name="broadcast_conversation",
        conversation_timeout=15 * 60,
    )


def get_broadcast_handlers() -> list:
    """Вернуть conversation и самостоятельные callback-хендлеры раздела."""
    return [
        get_broadcast_handler(),
        CallbackQueryHandler(list_groups, pattern="^bcast_group_list$"),
        CallbackQueryHandler(group_detail, pattern="^bcast_group_detail_"),
        CallbackQueryHandler(group_delete, pattern="^bcast_group_delete_"),
        CallbackQueryHandler(broadcast_history, pattern="^bcast_history$"),
        CallbackQueryHandler(
            control_broadcast, pattern="^bcast_(?:pause|resume|stop)_\\d+$"
        ),
    ]
