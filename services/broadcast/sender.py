"""Отправка одного таргета с матрицей ошибок Telegram."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import (
    BadRequest,
    ChatMigrated,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)

from services.broadcast.rate_limiter import BroadcastRateLimiter
from services.broadcast.repository import (
    BroadcastRecord,
    BroadcastRepository,
    TargetRecord,
)
from services.logger_config import get_logger

logger = get_logger(__name__)


class GlobalPauseGate:
    """Общая пауза воркера после Telegram RetryAfter."""

    def __init__(self) -> None:
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    async def pause(self, seconds: float) -> None:
        """Продлить глобальную паузу."""
        async with self._lock:
            self._paused_until = max(self._paused_until, time.monotonic() + seconds)

    async def wait(self) -> None:
        """Дождаться окончания общей паузы."""
        while True:
            delay = self._paused_until - time.monotonic()
            if delay <= 0:
                return
            await asyncio.sleep(delay)


class BroadcastSender:
    """Копирует сообщение или медиагруппу в один разрешённый чат."""

    def __init__(
        self,
        *,
        bot: Any,
        repository: BroadcastRepository,
        max_retries: int,
        pause_gate: GlobalPauseGate,
        rate_limiter: BroadcastRateLimiter,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.max_retries = max_retries
        self.pause_gate = pause_gate
        self.rate_limiter = rate_limiter

    async def send(self, broadcast: BroadcastRecord, target: TargetRecord) -> str:
        """Отправить один таргет; любая Telegram-ошибка изолирована."""
        current_target = target
        retries = 0
        while True:
            await self.pause_gate.wait()
            try:
                await self.rate_limiter.acquire()
                await self._copy_content(broadcast, current_target.chat_id)
            except ChatMigrated as exc:
                if retries >= self.max_retries:
                    return await self._fail(
                        current_target, "chat_migrated_retry_exhausted", exc
                    )
                retries += 1
                try:
                    current_target = await self.repository.migrate_chat(
                        current_target, exc.new_chat_id
                    )
                    await self.repository.increment_attempts(current_target.id)
                except Exception as migration_error:  # noqa: BLE001
                    return await self._fail(
                        current_target, "chat_migration_failed", migration_error
                    )
                continue
            except RetryAfter as exc:
                if retries >= self.max_retries:
                    return await self._fail(
                        current_target, "retry_after_exhausted", exc
                    )
                retries += 1
                delay = self._retry_after_seconds(exc) + 1.0
                await self.repository.increment_attempts(current_target.id)
                await self.pause_gate.pause(delay)
                logger.warning(
                    "broadcast.retry_after",
                    broadcast_id=broadcast.id,
                    chat_id=current_target.chat_id,
                    retry_after=delay,
                )
                continue
            except Forbidden as exc:
                await self.repository.target_failed(
                    current_target,
                    status="blocked",
                    error_code="forbidden",
                    error_message=str(exc),
                    deactivate=True,
                )
                logger.warning(
                    "broadcast.target_blocked",
                    broadcast_id=broadcast.id,
                    chat_id=current_target.chat_id,
                )
                return "blocked"
            except BadRequest as exc:
                deactivate = self._is_invalid_chat(exc)
                await self.repository.target_failed(
                    current_target,
                    status="failed",
                    error_code="bad_request",
                    error_message=str(exc),
                    deactivate=deactivate,
                )
                logger.warning(
                    "broadcast.bad_request",
                    broadcast_id=broadcast.id,
                    chat_id=current_target.chat_id,
                    deactivated=deactivate,
                )
                return "failed"
            except (TimedOut, NetworkError) as exc:
                if retries >= self.max_retries:
                    return await self._fail(
                        current_target, "network_retry_exhausted", exc
                    )
                delay = float(4**retries)
                retries += 1
                await self.repository.increment_attempts(current_target.id)
                logger.warning(
                    "broadcast.network_retry",
                    broadcast_id=broadcast.id,
                    chat_id=current_target.chat_id,
                    delay=delay,
                    attempt=retries,
                )
                await asyncio.sleep(delay)
                continue
            except TelegramError as exc:
                return await self._fail(current_target, "telegram_error", exc)
            except Exception as exc:  # noqa: BLE001 - граница одного таргета
                logger.exception(
                    "broadcast.unexpected_target_error",
                    broadcast_id=broadcast.id,
                    chat_id=current_target.chat_id,
                )
                return await self._fail(current_target, "unexpected_error", exc)
            else:
                await self.repository.target_succeeded(current_target)
                logger.info(
                    "broadcast.target_sent",
                    broadcast_id=broadcast.id,
                    chat_id=current_target.chat_id,
                )
                return "sent"

    async def _copy_content(self, broadcast: BroadcastRecord, chat_id: int) -> None:
        markup = self._build_markup(broadcast.reply_markup)
        if len(broadcast.source_message_ids) == 1:
            await self.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=broadcast.source_chat_id,
                message_id=broadcast.source_message_ids[0],
                reply_markup=markup,
                disable_notification=broadcast.disable_notification,
                protect_content=broadcast.protect_content,
            )
            return

        await self.bot.copy_messages(
            chat_id=chat_id,
            from_chat_id=broadcast.source_chat_id,
            message_ids=broadcast.source_message_ids,
            disable_notification=broadcast.disable_notification,
            protect_content=broadcast.protect_content,
        )
        if markup is not None:
            await self._send_album_buttons(chat_id, markup)

    async def _send_album_buttons(
        self, chat_id: int, markup: InlineKeyboardMarkup
    ) -> None:
        """Отправить кнопки к альбому отдельно, не дублируя уже ушедшие медиа."""
        for attempt in range(self.max_retries + 1):
            try:
                await self.rate_limiter.acquire()
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="Ссылки к публикации:",
                    reply_markup=markup,
                    disable_notification=True,
                )
                return
            except RetryAfter as exc:
                delay = self._retry_after_seconds(exc) + 1.0
                await self.pause_gate.pause(delay)
                await self.pause_gate.wait()
            except (TimedOut, NetworkError):
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(float(4**attempt))
            except TelegramError:
                break
        logger.warning("broadcast.album_buttons_failed", chat_id=chat_id)

    async def _fail(self, target: TargetRecord, code: str, exc: BaseException) -> str:
        try:
            await self.repository.target_failed(
                target,
                status="failed",
                error_code=code,
                error_message=str(exc),
            )
        except Exception:  # noqa: BLE001 - ошибка учёта не должна пробить batch
            logger.exception(
                "broadcast.target_failure_persist_failed",
                broadcast_id=target.broadcast_id,
                chat_id=target.chat_id,
                error_code=code,
            )
        logger.warning(
            "broadcast.target_failed",
            broadcast_id=target.broadcast_id,
            chat_id=target.chat_id,
            error_code=code,
        )
        return "failed"

    @staticmethod
    def _build_markup(
        value: list[list[dict[str, str]]] | None,
    ) -> InlineKeyboardMarkup | None:
        if not value:
            return None
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(item["text"], url=item["url"]) for item in row]
                for row in value
            ]
        )

    @staticmethod
    def _retry_after_seconds(exc: RetryAfter) -> float:
        value = exc.retry_after
        if isinstance(value, timedelta):
            return max(0.0, value.total_seconds())
        return max(0.0, float(value))

    @staticmethod
    def _is_invalid_chat(exc: BadRequest) -> bool:
        message = str(exc).casefold()
        invalid_markers = (
            "chat not found",
            "user is deactivated",
            "chat_id is empty",
            "peer_id_invalid",
            "bot was kicked",
        )
        return any(marker in message for marker in invalid_markers)
