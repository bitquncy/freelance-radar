"""Фоновый исполнитель безопасной очереди рассылок."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError

from services.broadcast.repository import (
    BroadcastRecord,
    BroadcastRepository,
    TargetRecord,
)
from services.broadcast.sender import BroadcastSender, GlobalPauseGate
from services.logger_config import get_logger

logger = get_logger(__name__)


class BroadcastRunner:
    """Исполняет due-рассылки батчами и продолжает после перезапуска."""

    def __init__(
        self,
        *,
        bot: Any,
        repository: BroadcastRepository,
        rate_limit: int,
        batch_size: int,
        max_retries: int,
        progress_interval: int,
        min_chat_interval_sec: int,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.rate_limit = max(1, min(rate_limit, 25))
        self.batch_size = max(1, min(batch_size, self.rate_limit))
        self.progress_interval = max(5, progress_interval)
        self.min_chat_interval_sec = max(60, min_chat_interval_sec)
        self.pause_gate = GlobalPauseGate()
        self.sender = BroadcastSender(
            bot=bot,
            repository=repository,
            max_retries=max_retries,
            pause_gate=self.pause_gate,
        )
        self._run_lock = asyncio.Lock()
        self._recovered = False
        self._last_progress_at: dict[int, float] = {}

    async def run_due(self) -> None:
        """Обработать все готовые кампании; параллельные тики схлопываются."""
        if self._run_lock.locked():
            return
        async with self._run_lock:
            if not self._recovered:
                recovered = await self.repository.recover_uncertain_targets()
                self._recovered = True
                if recovered:
                    logger.warning("broadcast.uncertain_targets_skipped", count=recovered)

            for broadcast_id in await self.repository.due_broadcast_ids():
                try:
                    await self._run_broadcast(broadcast_id)
                except Exception as exc:  # noqa: BLE001 - изоляция отдельных кампаний
                    logger.exception(
                        "broadcast.runner_failed", broadcast_id=broadcast_id
                    )
                    await self.repository.fail_broadcast(broadcast_id, str(exc))

    async def _run_broadcast(self, broadcast_id: int) -> None:
        broadcast = await self.repository.get_broadcast(broadcast_id)
        if broadcast is None:
            await self.repository.fail_broadcast(
                broadcast_id, "Исходное сообщение рассылки отсутствует"
            )
            return
        if not await self.repository.start(broadcast_id):
            return

        broadcast = await self.repository.get_broadcast(broadcast_id)
        if broadcast is None:
            return
        await self._update_progress(broadcast, force=True)

        while await self.repository.status(broadcast_id) == "running":
            batch = await self.repository.claim_targets(broadcast_id, self.batch_size)
            if not batch:
                counts = await self.repository.finish(broadcast_id)
                await self._update_progress(broadcast, force=True, final=True, counts=counts)
                return

            started = time.monotonic()
            await asyncio.gather(
                *(self._send_if_allowed(broadcast, target) for target in batch),
                return_exceptions=False,
            )
            await self.repository.sync_counts(broadcast_id)
            await self._update_progress(broadcast)

            # Батч не может превысить заданное среднее число сообщений в секунду.
            required_window = len(batch) / self.rate_limit
            remaining = required_window - (time.monotonic() - started)
            if remaining > 0:
                await asyncio.sleep(remaining)

        # Пауза и отмена замечаются не позднее завершения текущего батча.
        status = await self.repository.status(broadcast_id)
        await self._update_progress(
            broadcast,
            force=True,
            final=status == "cancelled",
        )

    async def _send_if_allowed(
        self, broadcast: BroadcastRecord, target: TargetRecord
    ) -> str:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.min_chat_interval_sec
        )
        if await self.repository.was_sent_recently(target.chat_id, cutoff.isoformat()):
            await self.repository.target_failed(
                target,
                status="skipped",
                error_code="chat_cooldown",
                error_message="Повторная отправка в чат ограничена безопасным кулдауном",
            )
            logger.info(
                "broadcast.target_skipped_cooldown",
                broadcast_id=broadcast.id,
                chat_id=target.chat_id,
            )
            return "skipped"
        return await self.sender.send(broadcast, target)

    async def _update_progress(
        self,
        broadcast: BroadcastRecord,
        *,
        force: bool = False,
        final: bool = False,
        counts: dict[str, int] | None = None,
    ) -> None:
        if not broadcast.progress_chat_id or not broadcast.progress_message_id:
            return
        now = time.monotonic()
        last = self._last_progress_at.get(broadcast.id, 0.0)
        if not force and now - last < self.progress_interval:
            return
        self._last_progress_at[broadcast.id] = now
        if counts is None:
            counts = await self.repository.sync_counts(broadcast.id)
        status = await self.repository.status(broadcast.id) or "unknown"

        done = counts["sent"] + counts["failed"] + counts["blocked"] + counts["skipped"]
        elapsed = self._elapsed_seconds(broadcast.started_at)
        title = "Рассылка завершена" if status == "done" else "Рассылка"
        if status == "cancelled":
            title = "Рассылка остановлена"
        elif status == "paused":
            title = "Рассылка на паузе"
        text = (
            f"📣 {title} #{broadcast.id}\n\n"
            f"Прогресс: {done}/{counts['total']}\n"
            f"✅ Отправлено: {counts['sent']}\n"
            f"⛔ Заблокировано: {counts['blocked']}\n"
            f"⚠️ Ошибки: {counts['failed']}\n"
            f"⏭ Пропущено: {counts['skipped']}\n"
            f"⏱ Длительность: {elapsed} сек."
        )
        reply_markup = None if final or status in {"done", "cancelled", "failed"} else self._controls(broadcast.id, status)
        try:
            await self.bot.edit_message_text(
                chat_id=broadcast.progress_chat_id,
                message_id=broadcast.progress_message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except BadRequest as exc:
            if "message is not modified" not in str(exc).casefold():
                logger.warning(
                    "broadcast.progress_bad_request",
                    broadcast_id=broadcast.id,
                    error=str(exc),
                )
        except TelegramError as exc:
            logger.warning(
                "broadcast.progress_update_failed",
                broadcast_id=broadcast.id,
                error=str(exc),
            )

    @staticmethod
    def _controls(broadcast_id: int, status: str) -> InlineKeyboardMarkup:
        if status == "paused":
            first = InlineKeyboardButton(
                "▶️ Продолжить", callback_data=f"bcast_resume_{broadcast_id}"
            )
        else:
            first = InlineKeyboardButton(
                "⏸ Пауза", callback_data=f"bcast_pause_{broadcast_id}"
            )
        return InlineKeyboardMarkup(
            [[first, InlineKeyboardButton("⏹ Стоп", callback_data=f"bcast_stop_{broadcast_id}")]]
        )

    @staticmethod
    def _elapsed_seconds(started_at: str | None) -> int:
        if not started_at:
            return 0
        try:
            started = datetime.fromisoformat(started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            return max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
        except ValueError:
            return 0
