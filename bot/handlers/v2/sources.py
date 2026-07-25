"""Source connections management (§3.1) with tariff limits (§7)."""
from typing import List

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import BaseHandler, CallbackQueryHandler, ContextTypes

from bot.handlers.v2.common import esc, get_or_create_user, pending
from core import tariffs
from core.models import ConnectionStatus, ExchangeConnection, Platform
from core.db import get_session_factory

PLATFORM_TITLES = {
    Platform.KWORK: "Kwork",
    Platform.FL_RU: "FL.ru",
    Platform.TG_CHANNEL: "TG-канал",
}

EXCHANGE_PLATFORMS = {p for p in Platform if p is not Platform.TG_CHANNEL}


def _sources_keyboard(connections: List[ExchangeConnection]) -> InlineKeyboardMarkup:
    rows = []
    for connection in connections:
        title = PLATFORM_TITLES.get(connection.platform, connection.platform.value)
        if connection.platform is Platform.TG_CHANNEL:
            title += f" {connection.settings.get('channel', '')}"
        state = "\U0001f7e2" if connection.status is ConnectionStatus.ACTIVE else "⏸"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{state} {title}", callback_data=f"v2s:toggle:{connection.id}"
                ),
                InlineKeyboardButton(
                    "\U0001f5d1", callback_data=f"v2s:del:{connection.id}"
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("➕ Kwork", callback_data="v2s:add:kwork"),
            InlineKeyboardButton("➕ FL.ru", callback_data="v2s:add:fl_ru"),
            InlineKeyboardButton("➕ TG-канал", callback_data="v2s:add:tg"),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def sources_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show connections list with add/toggle/delete controls."""
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    await query.answer()
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        result = await session.execute(
            select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)
        )
        connections = list(result.scalars().all())
        await session.commit()
    text = (
        "\U0001f4e1 <b>Источники</b>\n"
        "Радар мониторит подключённые источники и присылает новые заказы "
        "со скорингом."
        if connections
        else "\U0001f4e1 <b>Источники</b>\nПока ничего не подключено — добавьте первый источник."
    )
    await query.edit_message_text(
        text, parse_mode="HTML", reply_markup=_sources_keyboard(connections)
    )


async def source_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a connection, enforcing §7 limits."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    kind = query.data.split(":")[2]
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        tier = tariffs.effective_tier(user)
        result = await session.execute(
            select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)
        )
        connections = list(result.scalars().all())
        exchanges = sum(
            1 for c in connections if c.platform is not Platform.TG_CHANNEL
        )
        channels = sum(1 for c in connections if c.platform is Platform.TG_CHANNEL)

        if kind == "tg":
            if not tariffs.can_connect_tg_channel(tier, channels):
                await query.answer(
                    "Лимит TG-каналов на вашем тарифе исчерпан.", show_alert=True
                )
                return
            pending(context)["v2_add_channel"] = True
            await query.answer()
            await query.message.reply_text(  # type: ignore[union-attr]
                "Пришлите username канала (например, @freelance_orders)."
            )
            return

        platform = Platform.KWORK if kind == "kwork" else Platform.FL_RU
        if any(c.platform is platform for c in connections):
            await query.answer("Этот источник уже подключён.", show_alert=True)
            return
        if not tariffs.can_connect_exchange(tier, exchanges):
            await query.answer(
                "Лимит бирж на вашем тарифе исчерпан — апгрейд в /subscription.",
                show_alert=True,
            )
            return
        session.add(ExchangeConnection(user_id=user.id, platform=platform))
        await session.commit()
    await query.answer(f"{PLATFORM_TITLES[platform]} подключён.")
    await sources_menu(update, context)


async def source_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pause/resume a connection."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    connection_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        connection = await session.get(ExchangeConnection, connection_id)
        if connection is None or connection.user_id != user.id:
            await query.answer("Источник не найден.", show_alert=True)
            return
        connection.status = (
            ConnectionStatus.PAUSED
            if connection.status is ConnectionStatus.ACTIVE
            else ConnectionStatus.ACTIVE
        )
        await session.commit()
    await sources_menu(update, context)


async def source_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a connection."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    connection_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        connection = await session.get(ExchangeConnection, connection_id)
        if connection is not None and connection.user_id == user.id:
            await session.delete(connection)
            await session.commit()
    await sources_menu(update, context)


async def add_channel_from_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """Finish the TG-channel add flow started in :func:`source_add`.

    The tariff limit and duplicates are re-checked HERE, at save time — the
    button-tap check alone could be bypassed by delaying the text reply
    (limit) or by sending the same channel twice (duplicate).
    """
    if update.effective_user is None or update.message is None:
        return
    username = text.strip().split()[0]
    username = username.split("/")[-1]
    if not username.startswith("@"):
        username = f"@{username}"
    if len(username) < 4:
        await update.message.reply_text("Похоже, это не username канала.")
        return
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        result = await session.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user.id,
                ExchangeConnection.platform == Platform.TG_CHANNEL,
            )
        )
        channels = list(result.scalars().all())
        existing = {
            str(c.settings.get("channel", "")).casefold() for c in channels
        }
        if username.casefold() in existing:
            await update.message.reply_text("Этот канал уже подключён.")
            return
        tier = tariffs.effective_tier(user)
        if not tariffs.can_connect_tg_channel(tier, len(channels)):
            await update.message.reply_text(
                "Лимит TG-каналов на вашем тарифе исчерпан — апгрейд в /subscription."
            )
            return
        session.add(
            ExchangeConnection(
                user_id=user.id,
                platform=Platform.TG_CHANNEL,
                settings={"channel": username},
            )
        )
        await session.commit()
    await update.message.reply_text(
        f"Канал {esc(username)} подключён \U0001f4e1", parse_mode="HTML"
    )


def get_source_handlers() -> List[BaseHandler]:
    """Build source-management callback handlers."""
    return [
        CallbackQueryHandler(sources_menu, pattern=r"^v2s:menu$"),
        CallbackQueryHandler(source_add, pattern=r"^v2s:add:(kwork|fl_ru|tg)$"),
        CallbackQueryHandler(source_toggle, pattern=r"^v2s:toggle:\d+$"),
        CallbackQueryHandler(source_delete, pattern=r"^v2s:del:\d+$"),
    ]
