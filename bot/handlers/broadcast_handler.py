"""Broadcast handler for sending messages to chat groups."""
import aiosqlite
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)

from services.logger_config import get_logger
from bot.auth import owner_only
from db import queries
from config import DB_PATH, OWNER_CHAT_ID

logger = get_logger(__name__)

# Conversation states
(
    ENTERING_GROUP_NAME,
    SELECTING_GROUP_FOR_BROADCAST,
    ENTERING_BROADCAST_MESSAGE,
    CONFIRMING_BROADCAST,
    ADDING_CHAT_ID,
) = range(5)


# ─── Main menu ───────────────────────────────────────────────────────

@owner_only
async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show broadcast main menu."""
    await update.message.reply_text(
        "📢 **Рассылка сообщений**\n\n"
        "Выберите действие:",
        reply_markup=_main_keyboard(),
        parse_mode=None
    )


def _main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("➕ Создать группу чатов", callback_data="bcast_group_create")],
        [InlineKeyboardButton("📋 Мои группы", callback_data="bcast_group_list")],
        [InlineKeyboardButton("📨 Новая рассылка", callback_data="bcast_send_start")],
        [InlineKeyboardButton("📜 История рассылок", callback_data="bcast_history")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ─── Group CRUD ──────────────────────────────────────────────────────

@owner_only
async def create_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start creating a new chat group."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "➕ **Новая группа чатов**\n\n"
        "Введите название группы (например: \"Дизайн-каналы\"):\n\n"
        "/cancel — отмена",
        reply_markup=_cancel_kb(),
        parse_mode=None
    )
    return ENTERING_GROUP_NAME


@owner_only
async def save_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save group name."""
    name = update.message.text.strip()

    if len(name) > 100:
        await update.message.reply_text("❌ Название слишком длинное (макс 100 символов).")
        return ENTERING_GROUP_NAME

    async with aiosqlite.connect(DB_PATH) as db:
        group_id = await queries.create_chat_group(db, OWNER_CHAT_ID, name)

    await update.message.reply_text(
        f"✅ Группа «{name}» создана (ID: {group_id})\n\n"
        "Теперь добавьте чаты в группу. Отправьте:\n"
        "• Chat ID (например: `-1002006920508`)\n"
        "• @username канала (например: `@freelance_chat`)\n"
        "• URL канала (например: `https://t.me/freelance_chat`)\n\n"
        "/done — завершить добавление\n"
        "/cancel — отмена",
        reply_markup=_cancel_kb()
    )
    context.user_data['current_group_id'] = group_id
    return ADDING_CHAT_ID


@owner_only
async def add_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Add a chat ID to the current group."""
    chat_id = update.message.text.strip()
    group_id = context.user_data.get('current_group_id')

    if not group_id:
        await update.message.reply_text("❌ Группа не найдена. Начните заново.")
        return ConversationHandler.END

    # Parse URL or username to get chat_id
    resolved_id = await _resolve_chat_id(chat_id, context)

    if not resolved_id:
        await update.message.reply_text(
            f"❌ Не удалось определить chat_id для `{chat_id}`.\n"
            "Отправьте actual chat_id (например: `-1002006920508` или `@channel_name`).\n"
            "Или /done для завершения.",
            parse_mode=None
        )
        return ADDING_CHAT_ID

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await queries.add_chat_to_group(db, group_id, resolved_id, chat_id)
            await update.message.reply_text(
                f"✅ Чат `{resolved_id}` (original: {chat_id}) добавлен в группу.\n"
                "Отправьте следующий ID или /done.",
                parse_mode=None
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Ошибка: {e}\nПопробуйте другой ID или /done."
            )

    return ADDING_CHAT_ID


async def _resolve_chat_id(text: str, context) -> str:
    """Resolve chat URL or username to actual chat_id."""
    import re

    text = text.strip()

    # Check if it's already a numeric chat_id (e.g., -1002006920508)
    if re.match(r'^-?\d+$', text):
        return text

    # Check if it's a URL like https://t.me/channel_name
    url_match = re.match(r'https?://t\.me/([^/]+)', text)
    if url_match:
        username = url_match.group(1)
        if not username.startswith('@'):
            username = f"@{username}"
        # Try to resolve the username to a chat_id
        try:
            chat = await context.bot.get_chat(username)
            return str(chat.id)
        except Exception as e:
            logger.warning("broadcast.resolve_failed", text=text, error=str(e))
            return username  # Return the username as fallback

    # Check if it's a @username
    if text.startswith('@'):
        try:
            chat = await context.bot.get_chat(text)
            return str(chat.id)
        except Exception as e:
            logger.warning("broadcast.resolve_failed", text=text, error=str(e))
            return text  # Return as fallback

    # Unknown format
    return text


@owner_only
async def done_adding_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finish adding chats to the group."""
    group_id = context.user_data.get('current_group_id')

    async with aiosqlite.connect(DB_PATH) as db:
        members = await queries.get_chat_group_members(db, group_id)

    await update.message.reply_text(
        f"✅ Группа готова! Чатов: {len(members)}\n\n"
        "Выберите действие:",
        reply_markup=_main_keyboard()
    )

    context.user_data.pop('current_group_id', None)
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
            "📋 **Мои группы**\n\n"
            "Групп пока нет. Создайте первую!",
            reply_markup=_main_keyboard(),
            parse_mode=None
        )
        return

    text = "📋 **Мои группы чатов:**\n\n"
    keyboard = []
    for g in groups:
        # Get member count
        async with aiosqlite.connect(DB_PATH) as db:
            members = await queries.get_chat_group_members(db, g.id)
        count = len(members)
        text += f"• **{g.name}** (ID: {g.id}) — {count} чатов\n"
        keyboard.append([
            InlineKeyboardButton(
                f"👁 {g.name} ({count})",
                callback_data=f"bcast_group_detail_{g.id}"
            ),
            InlineKeyboardButton("🗑", callback_data=f"bcast_group_delete_{g.id}")
        ])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
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
        await query.edit_message_text("❌ Группа не найдена.")
        return

    text = f"👁 **Группа: {group.name}**\n\n"
    text += f"ID: {group.id}\n"
    text += f"Чатов: {len(members)}\n\n"

    if members:
        text += "**Чаты:**\n"
        for m in members[:20]:
            text += f"  • {m.chat_title or m.chat_id}\n"
        if len(members) > 20:
            text += f"  ... и ещё {len(members) - 20}\n"

    keyboard = [
        [InlineKeyboardButton("➕ Добавить чат", callback_data=f"bcast_group_add_chat_{group.id}")],
        [InlineKeyboardButton("🗑 Удалить чат", callback_data=f"bcast_group_remove_chat_{group.id}")],
        [InlineKeyboardButton("✏️ Переименовать", callback_data=f"bcast_group_rename_{group.id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="bcast_group_list")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
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
        "✅ Группа удалена.",
        reply_markup=_main_keyboard()
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
            "❌ Нет групп для рассылки.\n"
            "Сначала создайте группу чатов.",
            reply_markup=_main_keyboard()
        )
        return ConversationHandler.END

    text = "📨 **Выберите группу чатов для рассылки:**\n\n"
    keyboard = []
    for g in groups:
        async with aiosqlite.connect(DB_PATH) as db:
            members = await queries.get_chat_group_members(db, g.id)
        keyboard.append([
            InlineKeyboardButton(
                f"{g.name} ({len(members)} чатов)",
                callback_data=f"bcast_select_group_{g.id}"
            )
        ])
    keyboard.append([InlineKeyboardButton("◀️ Отмена", callback_data="bcast_cancel")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )
    return SELECTING_GROUP_FOR_BROADCAST


@owner_only
async def group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Group selected, ask for message."""
    query = update.callback_query
    await query.answer()

    group_id = int(query.data.replace("bcast_select_group_", ""))
    context.user_data['broadcast_group_id'] = group_id

    async with aiosqlite.connect(DB_PATH) as db:
        group = await queries.get_chat_group(db, group_id)
        members = await queries.get_chat_group_members(db, group_id)

    await query.edit_message_text(
        f"📨 **Группа: {group.name}** ({len(members)} чатов)\n\n"
        "Отправьте сообщение для рассылки.\n"
        "Поддерживается: текст, фото, документ.\n\n"
        "/cancel — отмена",
        reply_markup=_cancel_kb(),
        parse_mode=None
    )
    return ENTERING_BROADCAST_MESSAGE


@owner_only
async def receive_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive broadcast message and show preview."""
    message = update.message
    context.user_data['broadcast_message'] = message

    text = "📋 **Превью рассылки:**\n\n"
    if message.text:
        text += f"{message.text[:500]}{'...' if len(message.text) > 500 else ''}\n"
    elif message.photo:
        text += "📸 Фото\n"
        if message.caption:
            text += f"📝 Подпись: {message.caption[:200]}\n"
    elif message.document:
        text += "📄 Документ\n"
        if message.caption:
            text += f"📝 Подпись: {message.caption[:200]}\n"
    else:
        text += "⚠️ Неизвестный тип сообщения\n"

    group_id = context.user_data.get('broadcast_group_id')
    async with aiosqlite.connect(DB_PATH) as db:
        group = await queries.get_chat_group(db, group_id)
        members = await queries.get_chat_group_members(db, group_id)

    text += f"\n🎯 Группа: {group.name} ({len(members)} чатов)\n"
    text += "\nОтправить?"

    await update.message.reply_text(
        text,
        reply_markup=_confirm_keyboard(),
        parse_mode=None
    )
    return CONFIRMING_BROADCAST


@owner_only
async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm and execute broadcast."""
    query = update.callback_query
    await query.answer()

    if query.data == "bcast_confirm_yes":
        broadcast_msg = context.user_data.get('broadcast_message')
        group_id = context.user_data.get('broadcast_group_id')

        if not broadcast_msg or not group_id:
            await query.edit_message_text("❌ Ошибка: данные не найдены.")
            return ConversationHandler.END

        async with aiosqlite.connect(DB_PATH) as db:
            members = await queries.get_chat_group_members(db, group_id)
            group = await queries.get_chat_group(db, group_id)

        if not members:
            await query.edit_message_text(
                "❌ В группе нет чатов.",
                reply_markup=_main_keyboard()
            )
            return ConversationHandler.END

        # Send to all chats in the group
        sent_count = 0
        failed_count = 0

        for member in members:
            chat_id = member.chat_id
            try:
                if broadcast_msg.text:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=broadcast_msg.text
                    )
                elif broadcast_msg.photo:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=broadcast_msg.photo[-1].file_id,
                        caption=broadcast_msg.caption
                    )
                elif broadcast_msg.document:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=broadcast_msg.document.file_id,
                        caption=broadcast_msg.caption
                    )
                sent_count += 1
            except Exception as e:
                logger.warning("broadcast.send_failed", chat_id=chat_id, error=str(e))
                failed_count += 1

        # Save broadcast to history
        async with aiosqlite.connect(DB_PATH) as db:
            await queries.save_broadcast(
                db, group_id,
                message_text=broadcast_msg.text if broadcast_msg.text else None,
                message_type="text" if broadcast_msg.text else "photo" if broadcast_msg.photo else "document",
                file_id=broadcast_msg.photo[-1].file_id if broadcast_msg.photo else broadcast_msg.document.file_id if broadcast_msg.document else None,
                caption=broadcast_msg.caption,
                sent_count=sent_count,
                failed_count=failed_count,
                status="completed"
            )

        result_text = f"✅ **Рассылка завершена!**\n\n"
        result_text += f"📊 Отправлено: {sent_count}\n"
        result_text += f"❌ Ошибок: {failed_count}\n"
        result_text += f"👥 Всего чатов: {len(members)}\n"
        result_text += f"🎯 Группа: {group.name}"

        await query.edit_message_text(
            result_text,
            reply_markup=_main_keyboard(),
            parse_mode=None
        )
    else:
        await query.edit_message_text(
            "❌ Рассылка отменена.",
            reply_markup=_main_keyboard()
        )

    context.user_data.pop('broadcast_message', None)
    context.user_data.pop('broadcast_group_id', None)
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
            "📜 **История рассылок**\n\n"
            "Рассылок пока нет.",
            reply_markup=_main_keyboard(),
            parse_mode=None
        )
        return

    text = "📜 **История рассылок:**\n\n"
    keyboard = []
    for b in broadcasts[:20]:
        status_emoji = "✅" if b.status == "completed" else "⏳"
        text += f"{status_emoji} {b.created_at[:16]} — {b.sent_count} отправлено, {b.failed_count} ошибок\n"
    text += f"\nВсего: {len(broadcasts)}"

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )


# ─── Helpers ─────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    context.user_data.pop('broadcast_message', None)
    context.user_data.pop('broadcast_group_id', None)
    context.user_data.pop('current_group_id', None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ Операция отменена.",
            reply_markup=_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Операция отменена.",
            reply_markup=_main_keyboard()
        )
    return ConversationHandler.END


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel")]
    ])


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, отправить", callback_data="bcast_confirm_yes")],
        [InlineKeyboardButton("❌ Отмена", callback_data="bcast_confirm_no")]
    ])


def get_broadcast_handler() -> ConversationHandler:
    """Get the broadcast conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_group_start, pattern="^bcast_group_create$"),
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_broadcast_message),
                MessageHandler(filters.PHOTO, receive_broadcast_message),
                MessageHandler(filters.Document.ALL, receive_broadcast_message),
            ],
            CONFIRMING_BROADCAST: [
                CallbackQueryHandler(confirm_broadcast, pattern="^bcast_confirm_")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^bcast_cancel$"),
            CommandHandler("cancel", cancel),
        ],
        per_user=True,
        per_chat=True,
        name="broadcast_conversation",
    )
