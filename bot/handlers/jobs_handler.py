"""Jobs handler for viewing and managing vacancies."""
from typing import Optional
import aiosqlite
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, CallbackQueryHandler

from services.logger_config import get_logger
from bot.auth import owner_only
from bot.keyboards import (
    vacancy_keyboard, response_keyboard,
    vacancy_list_keyboard,
)
from db import queries
from services.response_generator import ResponseGenerator
from services.sender import SenderService
from services.formatters import format_vacancy_full
from config import DB_PATH, OWNER_CHAT_ID

logger = get_logger(__name__)

VACANCIES_PER_PAGE = 5


def _parse_kwork_id(data: str, prefix: str) -> Optional[str]:
    """Safely extract kwork_id from callback data."""
    try:
        return data.replace(prefix, "")
    except (AttributeError, TypeError) as e:
        logger.warning("callback_parse_error", data=data, prefix=prefix, error=str(e))
        return None


def _parse_int(data: str, prefix: str) -> Optional[int]:
    """Safely extract integer from callback data."""
    try:
        return int(data.replace(prefix, ""))
    except (ValueError, TypeError) as e:
        logger.warning("callback_parse_int_error", data=data, prefix=prefix, error=str(e))
        return None


@owner_only
async def jobs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    """Show jobs menu with pagination."""
    async with aiosqlite.connect(DB_PATH) as db:
        all_vacancies = await queries.get_unseen_vacancies(db, limit=100)
        stats = await queries.get_vacancy_stats(db)

    if not all_vacancies:
        text = "📋 Новых вакансий нет.\n\n"
        text += "📊 Статистика:\n"
        text += f"Всего: {stats.get('total', 0)}\n"
        text += f"Просмотрено: {stats.get('total', 0) - stats.get('unseen', 0)}\n"
        text += f"Откликнуто: {stats.get('responded', 0)}\n"
        text += f"High priority: {stats.get('high_priority', 0)}"
        await update.message.reply_text(text)
        return

    # Calculate pagination
    total_pages = max(1, (len(all_vacancies) + VACANCIES_PER_PAGE - 1) // VACANCIES_PER_PAGE)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * VACANCIES_PER_PAGE
    page_vacancies = all_vacancies[start_idx:start_idx + VACANCIES_PER_PAGE]

    text = f"📋 Найдено новых вакансий: {len(all_vacancies)}\n"
    text += f"📄 Страница {page}/{total_pages}"

    await update.message.reply_text(
        text,
        reply_markup=vacancy_list_keyboard(page, total_pages, page_vacancies)
    )


async def show_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE, kwork_id: str) -> None:
    """Show vacancy details with enhanced formatting."""
    async with aiosqlite.connect(DB_PATH) as db:
        vacancy = await queries.get_vacancy_by_kwork_id(db, kwork_id)

    if not vacancy:
        if update.callback_query:
            await update.callback_query.answer("Вакансия не найдена")
        return

    text = format_vacancy_full(vacancy)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=vacancy_keyboard(kwork_id),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=vacancy_keyboard(kwork_id),
            parse_mode="HTML",
        )


@owner_only
async def vacancy_suitable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark vacancy as suitable."""
    query = update.callback_query
    kwork_id = _parse_kwork_id(query.data, "vacancy_suitable_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.mark_vacancy_analyzed(db, kwork_id)

    await query.answer("Отмечено как подходящая")


@owner_only
async def vacancy_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Skip vacancy."""
    query = update.callback_query

    kwork_id = _parse_kwork_id(query.data, "vacancy_skip_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.mark_vacancy_analyzed(db, kwork_id)
        vacancies = await queries.get_unseen_vacancies(db, limit=1)

    if vacancies:
        await show_vacancy(update, context, vacancies[0].kwork_id)
    else:
        try:
            await query.edit_message_text("✅ Все вакансии просмотрены!")
        except (TelegramError, ValueError, TypeError):
            await query.answer("✅ Все вакансии просмотрены!", show_alert=True)


@owner_only
async def vacancy_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add vacancy and optionally customer to blacklist."""
    query = update.callback_query

    kwork_id = _parse_kwork_id(query.data, "vacancy_blacklist_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer()

    # Get vacancy details to also blacklist customer
    async with aiosqlite.connect(DB_PATH) as db:
        vacancy = await queries.get_vacancy_by_kwork_id(db, kwork_id)

    if vacancy:
        from services.blacklist import BlacklistService
        bs = BlacklistService(DB_PATH)
        # Blacklist the vacancy
        await bs.add_to_blacklist("vacancy", kwork_id, OWNER_CHAT_ID, reason="user_decision")
        # Blacklist the customer if orders count is available (proxy for customer id)
        if vacancy.customer_orders:
            customer_id = f"orders_{vacancy.customer_orders}"
            await bs.add_to_blacklist("customer", customer_id, OWNER_CHAT_ID, reason="user_decision")
        logger.info("jobs.blacklisted", kwork_id=kwork_id, customer_orders=vacancy.customer_orders)

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.mark_vacancy_filtered(db, kwork_id, "user_blacklisted")
        vacancies = await queries.get_unseen_vacancies(db, limit=1)

    if vacancies:
        await show_vacancy(update, context, vacancies[0].kwork_id)
    else:
        await query.edit_message_text("🚫 Добавлено в чёрный список. Все вакансии просмотрены!")


@owner_only
async def vacancy_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed vacancy view."""
    query = update.callback_query

    kwork_id = _parse_kwork_id(query.data, "vacancy_detail_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer()
    await show_vacancy(update, context, kwork_id)


@owner_only
async def vacancy_generate_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate response for vacancy with profile context."""
    query = update.callback_query

    kwork_id = _parse_kwork_id(query.data, "vacancy_generate_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        vacancy = await queries.get_vacancy_by_kwork_id(db, kwork_id)
        if not vacancy:
            await query.edit_message_text("❌ Вакансия не найдена")
            return

        await queries.mark_vacancy_analyzed(db, kwork_id)

        settings = await queries.get_user_settings(db, OWNER_CHAT_ID)
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        recent_responses = await queries.get_recent_responses(db, limit=10)

        custom_prompt = settings.response_prompt if settings else None

    await query.answer("Генерирую отклик...")

    # Generate response
    generator = ResponseGenerator()
    response_text = await generator.generate_response(
        vacancy,
        custom_prompt=custom_prompt,
        profile=profile,
        recent_responses=recent_responses
    )

    if not response_text:
        await query.edit_message_text("❌ Не удалось сгенерировать отклик")
        return

    # Save response to database
    from db.models import Response
    response = Response(
        id=None,
        vacancy_id=0,
        kwork_id=kwork_id,
        response_text=response_text,
        approved=False,
        sent=False
    )

    async with aiosqlite.connect(DB_PATH) as db:
        response_id = await queries.save_response(db, response)

    text = "💬 <b>Отклик готов</b>\n\n"
    text += f'🔗 <a href="{vacancy.url}">Открыть заказ</a>\n'
    text += f"🆔 ID: <code>{kwork_id}</code>\n\n"
    text += "Выберите действие:"

    await query.edit_message_text(
        text,
        reply_markup=response_keyboard(response_id, kwork_id),
        parse_mode="HTML",
    )


@owner_only
async def response_copy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show response text for manual copy-paste."""
    query = update.callback_query

    response_id = _parse_int(query.data, "response_copy_")
    if response_id is None:
        await query.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        response = await queries.get_response_by_id(db, response_id)

    if not response:
        await query.answer("Отклик не найден", show_alert=True)
        return

    await query.answer()

    import html as _html
    text = f"📝 <b>Скопируйте и вставьте на бирже:</b>\n\n<pre>{_html.escape(response.response_text)}</pre>"
    await query.message.reply_text(text, parse_mode="HTML")


@owner_only
async def response_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send response via Telegram."""
    query = update.callback_query

    response_id = _parse_int(query.data, "response_send_")
    if response_id is None:
        await query.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        response = await queries.get_response_by_id(db, response_id)
        if not response:
            await query.answer("Отклик не найден", show_alert=True)
            return

        vacancy = await queries.get_vacancy_by_kwork_id(db, response.kwork_id)

    if not vacancy:
        await query.edit_message_text("❌ Вакансия не найдена")
        return

    await query.answer()

    # Send via Telegram if it's a Telegram source
    if vacancy.source.startswith("telegram:"):
        sender = SenderService()
        try:
            chat_id = vacancy.source.replace("telegram:", "")
            success = await sender.send_message(chat_id, response.response_text)
            if success:
                async with aiosqlite.connect(DB_PATH) as db:
                    await queries.approve_response(db, response_id)
                    await queries.mark_response_sent(db, response_id)
                    await queries.mark_vacancy_responded(db, response.kwork_id)
                await query.edit_message_text("✅ Отклик отправлен!")
            else:
                await query.edit_message_text("❌ Не удалось отправить (кулдаун или ошибка)")
        finally:
            await sender.cleanup()
    else:
        # For Kwork, just show the text
        import html as _html
        text = f"📝 <b>Отклик для Kwork:</b>\n\n<pre>{_html.escape(response.response_text)}</pre>\n\n"
        text += "Скопируйте и вставьте на бирже вручную."
        await query.edit_message_text(text, parse_mode="HTML")

        async with aiosqlite.connect(DB_PATH) as db:
            await queries.approve_response(db, response_id)
            await queries.mark_vacancy_responded(db, response.kwork_id)


@owner_only
async def response_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edit response - show text for editing."""
    query = update.callback_query

    response_id = _parse_int(query.data, "response_edit_")
    if response_id is None:
        await query.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        response = await queries.get_response_by_id(db, response_id)

    if not response:
        await query.answer("Отклик не найден", show_alert=True)
        return

    await query.answer()

    import html as _html
    text = f"✏️ <b>Отредактируйте текст и отправьте:</b>\n\n<pre>{_html.escape(response.response_text)}</pre>"
    await query.message.reply_text(text, parse_mode="HTML")


@owner_only
async def vacancy_defer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Defer vacancy — mark as deferred for 30 minutes."""
    query = update.callback_query

    kwork_id = _parse_kwork_id(query.data, "vacancy_defer_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer("⏳ Отложено на 30 мин")

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.mark_vacancy_analyzed(db, kwork_id)

    await query.edit_message_text(
        "⏳ Вакансия отложена на 30 минут.\n\n"
        "Вы можете вернуться к ней через меню 📋 Вакансии."
    )


@owner_only
async def response_defer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Defer response - mark for later."""
    query = update.callback_query

    response_id = _parse_int(query.data, "response_defer_")
    if response_id is None:
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer("⏳ Отложено")

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.approve_response(db, response_id)

    await query.edit_message_text(
        "⏳ Отклик отложен.\n\n"
        "Вы можете вернуться к нему через меню 📋 Вакансии → Отложенные."
    )


@owner_only
async def response_mark_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark vacancy as responded manually by user."""
    query = update.callback_query

    kwork_id = _parse_kwork_id(query.data, "response_mark_sent_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.mark_vacancy_analyzed(db, kwork_id)
        await queries.mark_vacancy_responded(db, kwork_id)

    await query.answer("✅ Пометил как откликнутую", show_alert=True)


@owner_only
async def response_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel response."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("❌ Отклик отменён.")


@owner_only
async def vacancy_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate response and show for immediate copy-paste (high priority shortcut)."""
    query = update.callback_query

    kwork_id = _parse_kwork_id(query.data, "vacancy_send_")
    if not kwork_id:
        await query.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        vacancy = await queries.get_vacancy_by_kwork_id(db, kwork_id)
        if not vacancy:
            await query.edit_message_text("❌ Вакансия не найдена")
            return

        await queries.mark_vacancy_analyzed(db, kwork_id)

        settings = await queries.get_user_settings(db, OWNER_CHAT_ID)
        profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
        recent_responses = await queries.get_recent_responses(db, limit=10)

        custom_prompt = settings.response_prompt if settings else None

    await query.answer("Генерирую отклик...")

    generator = ResponseGenerator()
    response_text = await generator.generate_response(
        vacancy,
        custom_prompt=custom_prompt,
        profile=profile,
        recent_responses=recent_responses,
    )

    if not response_text:
        await query.edit_message_text("❌ Не удалось сгенерировать отклик")
        return

    import html as _html
    text = "🚀 <b>Отклик для Kwork</b>\n\n"
    text += f'<pre>{_html.escape(response_text)}</pre>\n\n'
    text += f'🔗 <a href="{vacancy.url}">Открыть заказ</a>\n'
    text += "Скопируйте и вставьте на бирже вручную."

    await query.edit_message_text(text, parse_mode="HTML")

    async with aiosqlite.connect(DB_PATH) as db:
        await queries.mark_vacancy_responded(db, kwork_id)


@owner_only
async def vacancy_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle vacancy page navigation."""
    query = update.callback_query

    page = _parse_int(query.data, "vacancy_page_")
    if page is None:
        await query.answer("Ошибка данных", show_alert=True)
        return
    await query.answer()
    await show_vacancy_list(update, context, page)


@owner_only
async def vacancy_page_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle vacancy page info (no-op)."""
    query = update.callback_query
    await query.answer("Используйте кнопки для навигации")


async def show_vacancy_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    """Show paginated vacancy list."""
    async with aiosqlite.connect(DB_PATH) as db:
        all_vacancies = await queries.get_unseen_vacancies(db, limit=100)

    if not all_vacancies:
        await update.callback_query.edit_message_text("📋 Новых вакансий нет.")
        return

    total_pages = max(1, (len(all_vacancies) + VACANCIES_PER_PAGE - 1) // VACANCIES_PER_PAGE)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * VACANCIES_PER_PAGE
    page_vacancies = all_vacancies[start_idx:start_idx + VACANCIES_PER_PAGE]

    text = f"📋 Найдено новых вакансий: {len(all_vacancies)}\n"
    text += f"📄 Страница {page}/{total_pages}"

    await update.callback_query.edit_message_text(
        text,
        reply_markup=vacancy_list_keyboard(page, total_pages, page_vacancies)
    )


def get_jobs_handlers():
    """Get jobs-related callback handlers."""
    return [
        CallbackQueryHandler(vacancy_suitable, pattern="^vacancy_suitable_"),
        CallbackQueryHandler(vacancy_skip, pattern="^vacancy_skip_"),
        CallbackQueryHandler(vacancy_blacklist, pattern="^vacancy_blacklist_"),
        CallbackQueryHandler(vacancy_detail, pattern="^vacancy_detail_"),
        CallbackQueryHandler(vacancy_generate_response, pattern="^vacancy_generate_"),
        CallbackQueryHandler(vacancy_defer, pattern="^vacancy_defer_"),
        CallbackQueryHandler(vacancy_send, pattern="^vacancy_send_"),
        CallbackQueryHandler(response_copy, pattern="^response_copy_"),
        CallbackQueryHandler(response_send, pattern="^response_send_"),
        CallbackQueryHandler(response_edit, pattern="^response_edit_"),
        CallbackQueryHandler(response_defer, pattern="^response_defer_"),
        CallbackQueryHandler(response_mark_sent, pattern="^response_mark_sent_"),
        CallbackQueryHandler(response_cancel, pattern="^response_cancel_"),
        CallbackQueryHandler(vacancy_page, pattern="^vacancy_page_"),
        CallbackQueryHandler(vacancy_page_info, pattern="^vacancy_page_info$"),
    ]
