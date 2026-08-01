"""Отправка одного таргета с матрицей ошибок Telegram."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any

from telegram.error import (
    BadRequest,
    ChatMigrated,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)

from services.broadcast.repository import BroadcastRecord, BroadcastRepository, TargetRecord
from services.logger_config import get_logger

logger = get_logger(__name__)


class GlobalPauseGate:
    """Общая пауза воркера после ответа Telegram RetryAfter."""

    def __init__(self) -> None:
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    async def pause(self, seconds: float) -> None:
        """Продлить глобальную паузу минимум на указанное число секунд."""
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
    """Копирует исходное сообщение в один разрешённый чат."""

    def __init__(
        self,
        *,
        bot: Any,
        repository: BroadcastRepository,
        max_retries: int,
        pause_gate: GlobalPauseGate,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.max_retries = max_retries
        self.pause_gate = pause_gate

    async def send(self, broadcast: BroadcastRecord, target: TargetRecord) -> str:
        """Отправить один таргет; исключения не выходят за границы метода."""
        current_target = target
        retries = 0
        while True:
            await self.pause_gate.wait()
            try:
                await self.bot.copy_message(
                    chat_id=current_target.chat_id,
                    from_chat_id=broadcast.source_chat_id,
                    message_id=broadcast.source_message_id,
                    disable_notification=broadcast.disable_notification,
                    protect_content=broadcast.protect_content,
                )
            except ChatMigrated as exc:
                if retries >= self.max_retries:
                    return await self._fail(current_target, "chat_migrated_retry_exhausted", exc)
                retries += 1
                try:
                    current_target = await self.repository.migrate_chat(
                        current_target, exc.new_chat_id
                    )
                    await self.repository.increment_attempts(current_target.id)
                except (ValueError, TypeError, aiosqlite.Error) as migration_error:
                    return await self._fail(
                        current_target, "chat_migration_failed", migration_error
                    )
                continue
            except RetryAfter as exc:
                if retries >= self.max_retries:
                    return await self._fail(current_target, "retry_after_exhausted", exc)
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
                    return await self._fail(current_target, "network_retry_exhausted", exc)
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
            except Exception as exc:  # noqa: BLE001 - граница изоляции одного таргета
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

    async def _fail(
        self, target: TargetRecord, code: str, exc: BaseException
    ) -> str:
        await self.repository.target_failed(
            target,
            status="failed",
            error_code=code,
            error_message=str(exc),
        )
        logger.warning(
            "broadcast.target_failed",
            broadcast_id=target.broadcast_id,
            chat_id=target.chat_id,
            error_code=code,
        )
        return "failed"

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


# ``aiosqlite`` импортируется ниже Telegram-исключений намеренно: он нужен
# только для узкой обработки ошибки миграции chat_id.
import aiosqlite  # noqa: E402
