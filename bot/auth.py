"""Authentication middleware for FreelanceRadar bot."""
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from services.logger_config import get_logger
from config import OWNER_CHAT_ID

logger = get_logger(__name__)


def check_owner(update: Update) -> bool:
    """Check if the user is the owner."""
    user = update.effective_user
    return user is not None and user.id == OWNER_CHAT_ID


async def deny_access(update: Update) -> None:
    """Send access denied message to unauthorized user."""
    user = update.effective_user
    unauthorized_id = user.id if user else None
    logger.warning(
        "auth.unauthorized_access_attempt",
        user_id=unauthorized_id,
    )
    if update.message:
        await update.message.reply_text(
            "\u26d4 \u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430 \u043a \u044d\u0442\u043e\u043c\u0443 \u0431\u043e\u0442\u0443."
        )
    elif update.callback_query:
        await update.callback_query.answer(
            "\u26d4 \u0414\u043e\u0441\u0442\u0443\u043f \u0437\u0430\u043f\u0440\u0435\u0449\u0451\u043d.", show_alert=True
        )


def owner_only(handler: Callable) -> Callable:
    """Decorator that restricts handler to owner only.

    Checks if update.effective_user.id matches OWNER_CHAT_ID.
    If not, sends an access denied message and skips the handler.
    """
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_owner(update):
            await deny_access(update)
            return None
        return await handler(update, context)
    return wrapper
