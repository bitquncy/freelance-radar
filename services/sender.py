"""Sender service for sending messages to Telegram chats with cooldown."""
import aiosqlite
from datetime import datetime
from typing import Optional

from services.logger_config import get_logger
from parsers.telegram_source import TelegramSourceParser
from db import queries
from config import DB_PATH, DEFAULT_COOLDOWN_SEC

logger = get_logger(__name__)


class SenderService:
    """Service for sending messages to Telegram chats with cooldown management."""

    def __init__(self):
        self.telegram_parser: Optional[TelegramSourceParser] = None

    async def send_message(
        self,
        chat_id: str,
        message: str,
        cooldown_seconds: Optional[int] = None
    ) -> bool:
        """
        Send message to Telegram chat if cooldown allows.

        Args:
            chat_id: Chat ID or username to send to
            message: Message text
            cooldown_seconds: Cooldown in seconds (uses default if None)

        Returns:
            True if sent successfully, False otherwise
        """
        if not chat_id or not message:
            logger.warning("sender.invalid_params", chat_id=chat_id, message_empty=not message)
            return False

        if cooldown_seconds is None:
            cooldown_seconds = DEFAULT_COOLDOWN_SEC

        async with aiosqlite.connect(DB_PATH) as db:
            # Check cooldown
            can_send = await queries.can_send_to_chat(db, chat_id, cooldown_seconds)

            if not can_send:
                logger.warning("sender.cooldown_active", chat_id=chat_id)
                return False

            # Initialize Telegram client if needed
            if not self.telegram_parser:
                self.telegram_parser = TelegramSourceParser()
                await self.telegram_parser.connect()

            # Send message
            try:
                success = await self.telegram_parser.send_message_to_chat(chat_id, message)
            except (ValueError, TypeError, ConnectionError, OSError, Exception) as e:
                logger.error("sender.send_error", chat_id=chat_id, error=str(e))
                return False

            if success:
                # Update cooldown
                await queries.update_chat_cooldown(db, chat_id, cooldown_seconds)
                logger.info("sender.message_sent", chat_id=chat_id, cooldown_updated=True)
                return True
            else:
                logger.error("sender.message_send_failed", chat_id=chat_id)
                return False

    async def get_remaining_cooldown(self, chat_id: str) -> Optional[int]:
        """
        Get remaining cooldown time in seconds for a chat.

        Args:
            chat_id: Chat ID to check

        Returns:
            Remaining seconds or None if no cooldown
        """
        async with aiosqlite.connect(DB_PATH) as db:
            cooldown = await queries.get_chat_cooldown(db, chat_id)

            if not cooldown:
                return None

            elapsed = (datetime.now() - cooldown.last_sent_at).total_seconds()
            remaining = cooldown.cooldown_seconds - elapsed

            return max(0, int(remaining))

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.telegram_parser:
            await self.telegram_parser.disconnect()
            self.telegram_parser = None
