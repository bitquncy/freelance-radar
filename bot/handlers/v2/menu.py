"""V2 main menu / dashboard — the single navigation hub (§4.2 low friction).

Every screen in the bot can return here, so the user is never stuck in a
dead-end message. The dashboard shows live state (subscription, sources,
portfolio, CRM) instead of a static button grid, because the most common
question after opening the bot is "работает ли радар прямо сейчас?".
"""
from typing import List, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import BaseHandler, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.handlers.v2.common import get_or_create_user
from core import crm, tariffs
from emoji_config import E, P, primary_button, success_button
from core.db import get_session_factory
from core.models import (
    ConnectionStatus,
    ExchangeConnection,
    PortfolioItem,
    Proposal,
    ProposalStatus,
    SubscriptionTier,
    User,
)

HELP_TEXT = (
    f"{E.HELP} <b>Как работает FreelanceRadar</b>\n\n"
    f"1️⃣ <b>Источники</b> — подключите биржи и Telegram-каналы с заказами.\n"
    f"2️⃣ <b>Портфолио</b> — добавьте кейсы. Только из них AI берёт факты для "
    "откликов, поэтому бот никогда не выдумывает ваш опыт.\n"
    f"3️⃣ <b>Радар</b> — каждые несколько минут проверяет новые заказы, считает "
    f"скоринг ({E.GREEN} / {E.YELLOW} / {E.RED}), выгодность по вашей ставке "
    "и присылает карточку.\n"
    f"4️⃣ <b>Отклик</b> — кнопка под карточкой: AI пишет черновик, вы правите и "
    "отправляете на бирже сами.\n"
    f"5️⃣ <b>CRM</b> — отправленные отклики попадают в воронку с напоминаниями.\n\n"
    "<b>Команды</b>\n"
    "/menu — главное меню\n"
    "/radar — настройка профиля (ставка, налоги, навыки)\n"
    "/portfolio — кейсы\n"
    "/clients — CRM и воронка\n"
    "/subscription — подписка и оплата\n"
    "/help — эта справка\n\n"
    f"Тариф один: Радар PRO — {tariffs.PRIMARY_PRICE_RUB} ₽/мес, "
    f"первые {tariffs.TRIAL_DAYS} дней бесплатно."
)


def main_menu_keyboard(onboarded: bool = True) -> InlineKeyboardMarkup:
    """The V2 dashboard menu."""
    rows: List[List[InlineKeyboardButton]] = []
    if not onboarded:
        # Единственное «главное» действие для новичка — зелёный акцент.
        rows.append(
            [
                success_button(
                    "Настроить профиль", icon=P.ROCKET, callback_data="v2:onboard"
                )
            ]
        )
    rows += [
        [
            primary_button("Источники", icon=P.RADAR, callback_data="v2s:menu"),
            primary_button("Портфолио", icon=P.BRIEFCASE, callback_data="v2pf:menu"),
        ],
        [
            primary_button("Клиенты", icon=P.PEOPLE, callback_data="v2c:list"),
            primary_button("Подписка", icon=P.STAR, callback_data="v2sub:info"),
        ],
        [
            primary_button("Обновить", icon=P.RELOAD, callback_data="v2:menu"),
            primary_button("Помощь", icon=P.HELP, callback_data="v2:help"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


async def _dashboard_stats(
    session: AsyncSession, user: User
) -> Tuple[int, int, int, int]:
    """Count sources, portfolio items, active clients and sent proposals."""
    sources = (
        await session.execute(
            select(func.count(ExchangeConnection.id)).where(
                ExchangeConnection.user_id == user.id,
                ExchangeConnection.status == ConnectionStatus.ACTIVE,
            )
        )
    ).scalar_one()
    portfolio = (
        await session.execute(
            select(func.count(PortfolioItem.id)).where(
                PortfolioItem.user_id == user.id
            )
        )
    ).scalar_one()
    clients = await crm.count_active_clients(session, user.id)
    sent = (
        await session.execute(
            select(func.count(Proposal.id)).where(
                Proposal.user_id == user.id,
                Proposal.status == ProposalStatus.SENT,
            )
        )
    ).scalar_one()
    return sources, portfolio, clients, sent


def _status_line(user: User) -> str:
    """One-line subscription status with the trial countdown."""
    tier = tariffs.effective_tier(user)
    left = tariffs.days_left(user)
    if tier is None:
        return f"{E.LOCK} Подписка неактивна — радар на паузе"
    if tier is SubscriptionTier.TRIAL:
        tail = f", осталось {left} дн." if left is not None else ""
        return f"{E.GIFT} Бесплатный период{tail}"
    tail = f", осталось {left} дн." if left is not None else ""
    return f"{E.STAR} Радар PRO активен{tail}"


def dashboard_text(
    user: User, sources: int, portfolio: int, clients: int, sent: int
) -> str:
    """Render the dashboard body with a next-step hint."""
    onboarded = user.target_hourly_rate is not None
    rate = f"{user.target_hourly_rate} ₽/ч" if onboarded else "не задана"
    radar_on = tariffs.effective_tier(user) is not None and sources > 0 and onboarded

    if not onboarded:
        hint = (
            f"{E.POINT_RIGHT} Начните с профиля: ставка и навыки — "
            "без них скоринг не считается."
        )
    elif sources == 0:
        hint = (
            f"{E.POINT_RIGHT} Подключите хотя бы один источник — "
            "радару пока негде искать заказы."
        )
    elif portfolio == 0:
        hint = (
            f"{E.POINT_RIGHT} Добавьте 1–2 кейса в портфолио, "
            "чтобы AI писал отклики по фактам."
        )
    elif tariffs.effective_tier(user) is None:
        hint = (
            f"{E.POINT_RIGHT} Продлите подписку, чтобы радар снова "
            "начал сканировать заказы."
        )
    else:
        hint = "Радар работает — новые подходящие заказы придут сюда автоматически."

    scan_line = (
        f"{E.GREEN} Сканирование включено"
        if radar_on
        else f"{E.PAUSE} Сканирование не активно"
    )
    return (
        f"{E.RADAR} <b>FreelanceRadar</b>\n"
        f"{_status_line(user)}\n"
        f"{scan_line}\n\n"
        f"<b>Источники:</b> {sources}   <b>Портфолио:</b> {portfolio}\n"
        f"<b>Клиенты в CRM:</b> {clients}   <b>Откликов отправлено:</b> {sent}\n"
        f"<b>Целевая ставка:</b> {rate}\n\n"
        f"{hint}"
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/menu and the «⬅️ В меню» / «🔄 Обновить» buttons."""
    if update.effective_user is None:
        return
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        stats = await _dashboard_stats(session, user)
        await session.commit()
        text = dashboard_text(user, *stats)
        keyboard = main_menu_keyboard(onboarded=user.target_hourly_rate is not None)

    if update.callback_query is not None:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode="HTML", reply_markup=keyboard
            )
        except Exception:  # noqa: BLE001 - "message is not modified" is benign
            pass
        return
    if update.message is not None:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=keyboard
        )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help screen with a way back to the menu."""
    keyboard = InlineKeyboardMarkup(
        [
            [primary_button("В меню", icon=P.BACK, callback_data="v2:menu")]
        ]
    )
    if update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            HELP_TEXT, parse_mode="HTML", reply_markup=keyboard
        )
    elif update.message is not None:
        await update.message.reply_text(
            HELP_TEXT, parse_mode="HTML", reply_markup=keyboard
        )


def get_menu_handlers() -> List[BaseHandler]:
    """Build menu handlers."""
    return [
        CommandHandler("menu", show_menu),
        CallbackQueryHandler(show_menu, pattern=r"^v2:menu$"),
        CallbackQueryHandler(show_help, pattern=r"^v2:help$"),
    ]
