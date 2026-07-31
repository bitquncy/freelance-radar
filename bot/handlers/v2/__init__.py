"""V2 bot handlers: onboarding, portfolio, proposals, CRM, subscription.

Registered only when ``RADAR_V2_ENABLED`` is on — the legacy single-owner
bot behavior is untouched by default (AGENTS.md §12.4: scope discipline).
"""
from telegram import BotCommand
from telegram.ext import Application

from emoji_config import P

HANDLER_GROUP = 5

#: Shown in Telegram's native command menu (the ☰ button) — discoverability
#: without the user having to read documentation.
#: Описания команд — plain Unicode: Telegram не парсит здесь HTML,
#: поэтому <tg-emoji> протёк бы как текст.
BOT_COMMANDS = [
    BotCommand("menu", f"{P.RADAR} Главное меню и статус радара"),
    BotCommand("radar", f"{P.SETTINGS} Профиль: ставка, налоги, навыки"),
    BotCommand("portfolio", f"{P.BRIEFCASE} Портфолио для AI-откликов"),
    BotCommand("clients", f"{P.PEOPLE} CRM и воронка клиентов"),
    BotCommand("subscription", f"{P.STAR} Подписка и оплата"),
    BotCommand("help", f"{P.HELP} Как это работает"),
]


async def publish_bot_commands(application: Application) -> None:
    """Push the command list to Telegram (best-effort, never fatal).

    A failure here only costs the ☰ hints, so a network hiccup at startup
    must not prevent the bot from serving updates.
    """
    from services.logger_config import get_logger

    try:
        await application.bot.set_my_commands(BOT_COMMANDS)
    except Exception as exc:  # noqa: BLE001 - cosmetic feature, log and go on
        get_logger(__name__).warning("v2.set_commands_failed", error=str(exc))


def register_v2_handlers(application: Application) -> None:
    """Attach all V2 handlers to the application (group 5, no legacy clashes)."""
    from bot.handlers.v2.crm_handlers import get_crm_handlers
    from bot.handlers.v2.menu import get_menu_handlers
    from bot.handlers.v2.onboarding import get_onboarding_handlers
    from bot.handlers.v2.payments import get_payment_handlers
    from bot.handlers.v2.portfolio import get_portfolio_handlers
    from bot.handlers.v2.proposals import get_proposal_handlers
    from bot.handlers.v2.router import get_text_router
    from bot.handlers.v2.sources import get_source_handlers
    from bot.handlers.v2.subscription import get_subscription_handlers

    # Conversations survive restarts only when the application has a
    # persistence backend configured (main.py wires PicklePersistence).
    persistent = application.persistence is not None
    handlers = (
        get_menu_handlers()
        + get_onboarding_handlers(persistent=persistent)
        + get_portfolio_handlers(persistent=persistent)
        + get_source_handlers()
        + get_proposal_handlers()
        + get_crm_handlers()
        + get_subscription_handlers()
        + get_payment_handlers()
        + [get_text_router()]
    )
    for handler in handlers:
        application.add_handler(handler, group=HANDLER_GROUP)
