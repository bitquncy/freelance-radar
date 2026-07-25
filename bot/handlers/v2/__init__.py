"""V2 bot handlers: onboarding, portfolio, proposals, CRM, subscription.

Registered only when ``RADAR_V2_ENABLED`` is on — the legacy single-owner
bot behavior is untouched by default (AGENTS.md §12.4: scope discipline).
"""
from telegram.ext import Application

HANDLER_GROUP = 5


def register_v2_handlers(application: Application) -> None:
    """Attach all V2 handlers to the application (group 5, no legacy clashes)."""
    from bot.handlers.v2.crm_handlers import get_crm_handlers
    from bot.handlers.v2.onboarding import get_onboarding_handlers
    from bot.handlers.v2.portfolio import get_portfolio_handlers
    from bot.handlers.v2.proposals import get_proposal_handlers
    from bot.handlers.v2.router import get_text_router
    from bot.handlers.v2.sources import get_source_handlers
    from bot.handlers.v2.subscription import get_subscription_handlers

    handlers = (
        get_onboarding_handlers()
        + get_portfolio_handlers()
        + get_source_handlers()
        + get_proposal_handlers()
        + get_crm_handlers()
        + get_subscription_handlers()
        + [get_text_router()]
    )
    for handler in handlers:
        application.add_handler(handler, group=HANDLER_GROUP)
