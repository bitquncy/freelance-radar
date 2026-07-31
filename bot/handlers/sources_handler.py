"""Sources handler for managing monitoring sources."""
import aiosqlite
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

from services.logger_config import get_logger
from bot.auth import owner_only
from bot.keyboards import sources_keyboard, source_type_keyboard, cancel_keyboard
from db import queries
from db.models import Source
from config import DB_PATH
from emoji_config import P

logger = get_logger(__name__)

# Conversation states
SELECTING_SOURCE_TYPE, ENTERING_SOURCE_NAME, ENTERING_SOURCE_URL = range(3)


@owner_only
async def sources_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show sources management menu."""
    await update.message.reply_text(
        f"{P.RADAR} Управление источниками вакансий",
        reply_markup=sources_keyboard()
    )


@owner_only
async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all sources."""
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        sources = await queries.get_all_sources(db)

    if not sources:
        await query.edit_message_text(
            f"{P.LIST} Источники не настроены.\n\nДобавьте первый источник для мониторинга.",
            reply_markup=sources_keyboard()
        )
        return

    text = f"{P.LIST} Список источников:\n\n"
    for source in sources:
        status = f"{P.CHECK}" if source.enabled else f"{P.PAUSE}"
        text += f"{status} {source.name} ({source.source_type})\n"
        if source.urls_list:
            text += f"   Каналы ({len(source.urls_list)}):\n"
            for url in source.urls_list:
                text += f"   • {url}\n"
        elif source.url:
            text += f"   URL: {source.url}\n"
        text += f"   ID: {source.id}\n\n"

    text += "\nВыберите ID источника для управления или добавьте новый."

    await query.edit_message_text(text, reply_markup=sources_keyboard())


async def add_source_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start adding a new source."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "Выберите тип источника:",
        reply_markup=source_type_keyboard()
    )

    return SELECTING_SOURCE_TYPE


async def source_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle source type selection."""
    query = update.callback_query
    await query.answer()

    source_type = query.data.replace("source_type_", "")
    context.user_data["source_type"] = source_type

    await query.edit_message_text(
        f"Вы выбрали: {source_type}\n\nВведите название источника:",
        reply_markup=cancel_keyboard()
    )

    return ENTERING_SOURCE_NAME


async def source_name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle source name input."""
    source_name = update.message.text.strip()
    context.user_data["source_name"] = source_name

    source_type = context.user_data.get("source_type")

    if source_type == "kwork":
        # Kwork doesn't need URL, save immediately
        await save_source(update, context)
        return ConversationHandler.END
    else:
        # Telegram needs URL(s)
        await update.message.reply_text(
            "Введите URL Telegram-канала/чата (можно несколько через запятую):\n"
            "Например: https://t.me/channel1, https://t.me/channel2",
            reply_markup=cancel_keyboard()
        )
        return ENTERING_SOURCE_URL


async def source_url_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle source URL input (supports multiple URLs comma-separated)."""
    source_url = update.message.text.strip()
    context.user_data["source_url"] = source_url

    # Parse multiple URLs
    urls = [u.strip() for u in source_url.split(",") if u.strip()]

    if len(urls) == 1:
        context.user_data["source_url"] = urls[0]
        context.user_data["source_urls"] = None
    else:
        context.user_data["source_url"] = urls[0]
        import json
        context.user_data["source_urls"] = json.dumps(urls, ensure_ascii=False)

    await save_source(update, context)
    return ConversationHandler.END


async def save_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save the new source to database."""
    source_type = context.user_data.get("source_type")
    source_name = context.user_data.get("source_name")
    source_url = context.user_data.get("source_url")
    source_urls = context.user_data.get("source_urls")

    source = Source(
        id=None,
        name=source_name,
        source_type=source_type,
        url=source_url,
        enabled=True,
        urls=source_urls
    )

    async with aiosqlite.connect(DB_PATH) as db:
        source_id = await queries.add_source(db, source)

    await update.message.reply_text(
        f"{P.CHECK} Источник '{source_name}' успешно добавлен!\n\nID: {source_id}",
        reply_markup=sources_keyboard()
    )

    # Clear user data
    context.user_data.clear()


@owner_only
async def toggle_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle source enabled status."""
    query = update.callback_query

    try:
        source_id = int(query.data.replace("toggle_source_", ""))
    except (ValueError, TypeError):
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.toggle_source(db, source_id)

    await query.edit_message_text(
        f"{P.CHECK} Статус источника изменён.",
        reply_markup=sources_keyboard()
    )


@owner_only
async def delete_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a source."""
    query = update.callback_query

    try:
        source_id = int(query.data.replace("delete_source_", ""))
    except (ValueError, TypeError):
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.delete_source(db, source_id)

    await query.edit_message_text(
        f"{P.TRASH} Источник удалён.",
        reply_markup=sources_keyboard()
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            f"{P.CROSS} Операция отменена.",
            reply_markup=sources_keyboard()
        )
    else:
        await update.message.reply_text(
            f"{P.CROSS} Операция отменена.",
            reply_markup=sources_keyboard()
        )

    context.user_data.clear()
    return ConversationHandler.END


def get_sources_handler() -> ConversationHandler:
    """Get the sources conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_source_start, pattern="^add_source$")
        ],
        states={
            SELECTING_SOURCE_TYPE: [
                CallbackQueryHandler(source_type_selected, pattern="^source_type_")
            ],
            ENTERING_SOURCE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, source_name_entered)
            ],
            ENTERING_SOURCE_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, source_url_entered)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^cancel$")
        ],
        per_user=True,
        per_chat=True,
        name="sources_conversation",
    )
