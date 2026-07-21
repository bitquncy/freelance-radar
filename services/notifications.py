"""Notification service for sending vacancy alerts to Telegram."""
from telegram.error import TelegramError
from telegram.ext import Application

from services.logger_config import get_logger
from services.formatters import format_vacancy_notification
from services.blacklist import BlacklistService
from bot.keyboards import quick_vacancy_actions_keyboard
from config import DB_PATH, OWNER_CHAT_ID

logger = get_logger(__name__)


async def notify_new_vacancy(
    application: Application,
    vacancy,
    analysis: dict,
) -> None:
    """Send notification about new vacancy with quick actions."""
    bs = BlacklistService(DB_PATH)
    customer_id = None
    if vacancy.customer_orders:
        customer_id = f"orders_{vacancy.customer_orders}"
    if await bs.check_vacancy(vacancy.kwork_id, customer_id):
        logger.info(
            "bot.notification_skipped_blacklist",
            kwork_id=vacancy.kwork_id,
            customer_id=customer_id,
        )
        return

    text = format_vacancy_notification(vacancy, analysis)

    try:
        await application.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=text,
            reply_markup=quick_vacancy_actions_keyboard(
                vacancy.kwork_id,
                priority=analysis.get("priority", "low"),
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info(
            "bot.notification_sent",
            kwork_id=vacancy.kwork_id,
            priority=analysis.get("priority"),
            score=analysis.get("score"),
        )
    except (TelegramError, ValueError, TypeError) as e:
        logger.error("bot.notification_failed", kwork_id=vacancy.kwork_id, error=str(e))
