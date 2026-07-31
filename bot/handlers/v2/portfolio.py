"""Portfolio management — the only source of facts for proposals (§2.4, §6.4)."""
from typing import List

from sqlalchemy import select
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import (
    BaseHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.v2.common import esc, get_or_create_user, pending
from core.db import get_session_factory
from core.models import PortfolioItem
from emoji_config import E, P, danger_button, primary_button, success_button

P_TITLE, P_DESC, P_TAGS = range(3)


def _portfolio_keyboard(items: List[PortfolioItem]) -> InlineKeyboardMarkup:
    rows = [
        [
            danger_button(
                item.title[:30], icon=P.TRASH, callback_data=f"v2pf:del:{item.id}"
            )
        ]
        for item in items
    ]
    rows.append(
        [success_button("Добавить кейс", icon=P.PLUS, callback_data="v2pf:add")]
    )
    rows.append([primary_button("В меню", icon=P.BACK, callback_data="v2:menu")])
    return InlineKeyboardMarkup(rows)


def _render_list(items: List[PortfolioItem]) -> str:
    if not items:
        return (
            f"{E.BRIEFCASE} <b>Портфолио</b>\n"
            "Пока пусто. Добавьте кейсы — отклики строятся только на фактах "
            "из портфолио и без него AI-генерация недоступна."
        )
    lines = [f"{E.BRIEFCASE} <b>Портфолио</b>"]
    for item in items:
        tags = f" [{', '.join(item.tags)}]" if item.tags else ""
        lines.append(f"• <b>{esc(item.title)}</b>{esc(tags)}")
        if item.description:
            lines.append(f"  {esc(item.description[:120])}")
    return "\n".join(lines)


async def portfolio_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/portfolio — list cases."""
    if update.effective_user is None:
        return
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        result = await session.execute(
            select(PortfolioItem).where(PortfolioItem.user_id == user.id)
        )
        items = list(result.scalars().all())
        await session.commit()
    if update.message is not None:
        await update.message.reply_text(
            _render_list(items),
            parse_mode="HTML",
            reply_markup=_portfolio_keyboard(items),
        )
    elif update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            _render_list(items),
            parse_mode="HTML",
            reply_markup=_portfolio_keyboard(items),
        )


async def portfolio_add_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Start the add-case conversation."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    await query.message.reply_text(  # type: ignore[union-attr]
        "Название кейса? (например: «Бот записи для барбершопа»)"
    )
    return P_TITLE


async def portfolio_add_title(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Collect the case title."""
    if update.message is None or not update.message.text:
        return P_TITLE
    pending(context)["v2_pf_title"] = update.message.text.strip()[:200]
    await update.message.reply_text(
        "Короткое описание: что сделали и какой результат получил клиент?"
    )
    return P_DESC


async def portfolio_add_desc(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Collect the case description."""
    if update.message is None or not update.message.text:
        return P_DESC
    pending(context)["v2_pf_desc"] = update.message.text.strip()[:1500]
    await update.message.reply_text(
        "Теги через запятую (python, боты, ...) или «-», чтобы пропустить."
    )
    return P_TAGS


async def portfolio_add_tags(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Collect tags and save the case."""
    if update.message is None or update.message.text is None:
        return P_TAGS
    if update.effective_user is None:
        return ConversationHandler.END
    raw = update.message.text.strip()
    tags = (
        []
        if raw == "-"
        else [t.strip() for t in raw.split(",") if t.strip()][:15]
    )
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        session.add(
            PortfolioItem(
                user_id=user.id,
                title=pending(context).pop("v2_pf_title", "Кейс"),
                description=pending(context).pop("v2_pf_desc", ""),
                tags=tags,
            )
        )
        await session.commit()
    await update.message.reply_text(
        f"{P.CHECK} Кейс сохранён. Список: /portfolio"
    )
    return ConversationHandler.END


async def portfolio_add_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel the add-case flow."""
    pending(context).pop("v2_pf_title", None)
    pending(context).pop("v2_pf_desc", None)
    if update.message is not None:
        await update.message.reply_text(f"{P.CROSS} Добавление кейса отменено.")
    return ConversationHandler.END


async def portfolio_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Delete a case by button."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    item_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        item = await session.get(PortfolioItem, item_id)
        if item is not None and item.user_id == user.id:
            await session.delete(item)
            await session.commit()
    await portfolio_command(update, context)


def get_portfolio_handlers(persistent: bool = False) -> List[BaseHandler]:
    """Build portfolio handlers.

    Args:
        persistent: Persist the add-case conversation across restarts
            (requires an application-level persistence backend).
    """
    add_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(portfolio_add_start, pattern=r"^v2pf:add$")],
        states={
            P_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, portfolio_add_title)
            ],
            P_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, portfolio_add_desc)
            ],
            P_TAGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, portfolio_add_tags)
            ],
        },
        fallbacks=[CommandHandler("cancel", portfolio_add_cancel)],
        name="v2_portfolio_add",
        persistent=persistent,
    )
    return [
        CommandHandler("portfolio", portfolio_command),
        CallbackQueryHandler(portfolio_command, pattern=r"^v2pf:menu$"),
        add_conversation,
        CallbackQueryHandler(portfolio_delete, pattern=r"^v2pf:del:\d+$"),
    ]
