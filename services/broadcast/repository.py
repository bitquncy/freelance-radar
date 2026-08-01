"""Хранилище устойчивой очереди рассылок.

Статус таргета является источником истины. Перед внешним вызовом Telegram таргет
атомарно переводится в ``sending``. Если процесс завершится в этот момент, такой
таргет будет помечен ``skipped`` при следующем запуске и не будет отправлен
повторно: для рассылки выбран приоритет отсутствия дублей (at-most-once).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiosqlite


def utcnow_iso() -> str:
    """Вернуть текущий момент UTC в формате ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BroadcastRecord:
    """Сохранённая рассылка, готовая к исполнению."""

    id: int
    user_id: int
    group_id: int
    status: str
    source_chat_id: str
    source_message_id: int
    scheduled_at: Optional[str]
    started_at: Optional[str]
    progress_chat_id: Optional[str]
    progress_message_id: Optional[int]
    disable_notification: bool
    protect_content: bool


@dataclass(frozen=True)
class TargetRecord:
    """Один получатель рассылки."""

    id: int
    broadcast_id: int
    chat_id: str
    attempts: int


class BroadcastRepository:
    """Операции над очередью рассылок в legacy SQLite-хранилище."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def create_broadcast(
        self,
        *,
        user_id: int,
        group_id: int,
        source_chat_id: int | str,
        source_message_id: int,
        progress_chat_id: int | str,
        progress_message_id: int,
        scheduled_at: Optional[datetime] = None,
        disable_notification: bool = False,
        protect_content: bool = False,
    ) -> tuple[int, int]:
        """Создать рассылку и неизменяемый снимок активной аудитории."""
        created_at = utcnow_iso()
        scheduled_iso = scheduled_at.astimezone(timezone.utc).isoformat() if scheduled_at else None
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                INSERT INTO broadcasts (
                    user_id, group_id, message_type, status, source_chat_id,
                    source_message_id, scheduled_at, disable_notification,
                    protect_content, progress_chat_id, progress_message_id,
                    created_at
                ) VALUES (?, ?, 'copy', 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    group_id,
                    str(source_chat_id),
                    source_message_id,
                    scheduled_iso,
                    int(disable_notification),
                    int(protect_content),
                    str(progress_chat_id),
                    progress_message_id,
                    created_at,
                ),
            )
            broadcast_id = int(cursor.lastrowid)
            await db.execute(
                """
                INSERT OR IGNORE INTO broadcast_targets (
                    broadcast_id, chat_id, status, attempts, created_at
                )
                SELECT ?, chat_id, 'pending', 0, ?
                FROM chat_group_members
                WHERE group_id = ? AND is_active = 1
                GROUP BY chat_id
                """,
                (broadcast_id, created_at, group_id),
            )
            cursor = await db.execute(
                "SELECT COUNT(*) FROM broadcast_targets WHERE broadcast_id = ?",
                (broadcast_id,),
            )
            total = int((await cursor.fetchone())[0])
            await db.execute(
                "UPDATE broadcasts SET total_count = ? WHERE id = ?",
                (total, broadcast_id),
            )
            await db.commit()
        return broadcast_id, total

    async def recover_uncertain_targets(self) -> int:
        """Не повторять таргеты, которые могли уйти до аварийного завершения."""
        now = utcnow_iso()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE broadcast_targets
                SET status = 'skipped', error_code = 'uncertain_after_restart',
                    error_message = 'Не повторено после перезапуска во избежание дубля'
                WHERE status = 'sending'
                """
            )
            changed = cursor.rowcount
            await db.execute(
                """
                UPDATE broadcasts
                SET last_error = COALESCE(last_error, ?)
                WHERE status = 'running'
                """,
                (f"Восстановление очереди {now}: неоднозначные таргеты пропущены",),
            )
            await db.commit()
        return max(0, changed)

    async def due_broadcast_ids(self, limit: int = 10) -> list[int]:
        """Получить поставленные в очередь и запущенные рассылки по времени."""
        now = utcnow_iso()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT id FROM broadcasts
                WHERE status IN ('queued', 'running')
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY created_at
                LIMIT ?
                """,
                (now, limit),
            )
            return [int(row[0]) for row in await cursor.fetchall()]

    async def get_broadcast(self, broadcast_id: int) -> Optional[BroadcastRecord]:
        """Загрузить рассылку по идентификатору."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, user_id, group_id, status, source_chat_id,
                       source_message_id, scheduled_at, started_at,
                       progress_chat_id, progress_message_id,
                       disable_notification, protect_content
                FROM broadcasts WHERE id = ?
                """,
                (broadcast_id,),
            )
            row = await cursor.fetchone()
        if row is None or row["source_chat_id"] is None or row["source_message_id"] is None:
            return None
        return BroadcastRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            group_id=int(row["group_id"]),
            status=str(row["status"]),
            source_chat_id=str(row["source_chat_id"]),
            source_message_id=int(row["source_message_id"]),
            scheduled_at=row["scheduled_at"],
            started_at=row["started_at"],
            progress_chat_id=row["progress_chat_id"],
            progress_message_id=row["progress_message_id"],
            disable_notification=bool(row["disable_notification"]),
            protect_content=bool(row["protect_content"]),
        )

    async def start(self, broadcast_id: int) -> bool:
        """Перевести ожидающую рассылку в running, если она не остановлена."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE broadcasts
                SET status = 'running', started_at = COALESCE(started_at, ?)
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (utcnow_iso(), broadcast_id),
            )
            await db.commit()
        return cursor.rowcount > 0

    async def claim_targets(self, broadcast_id: int, limit: int) -> list[TargetRecord]:
        """Атомарно зарезервировать следующий батч таргетов."""
        claimed_at = utcnow_iso()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT id, broadcast_id, chat_id, attempts
                FROM broadcast_targets
                WHERE broadcast_id = ? AND status = 'pending'
                ORDER BY id
                LIMIT ?
                """,
                (broadcast_id, limit),
            )
            rows = await cursor.fetchall()
            claimed: list[TargetRecord] = []
            for row in rows:
                cursor = await db.execute(
                    """
                    UPDATE broadcast_targets
                    SET status = 'sending', attempts = attempts + 1, claimed_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (claimed_at, row[0]),
                )
                if cursor.rowcount:
                    claimed.append(
                        TargetRecord(
                            id=int(row[0]),
                            broadcast_id=int(row[1]),
                            chat_id=str(row[2]),
                            attempts=int(row[3]) + 1,
                        )
                    )
            await db.commit()
        return claimed

    async def increment_attempts(self, target_id: int) -> int:
        """Учесть дополнительную попытку после временной ошибки."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE broadcast_targets SET attempts = attempts + 1 WHERE id = ?",
                (target_id,),
            )
            cursor = await db.execute(
                "SELECT attempts FROM broadcast_targets WHERE id = ?", (target_id,)
            )
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]) if row else 0

    async def target_succeeded(self, target: TargetRecord) -> None:
        """Зафиксировать успешную отправку и кулдаун чата."""
        now = utcnow_iso()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE broadcast_targets
                SET status = 'sent', sent_at = ?, error_code = NULL, error_message = NULL
                WHERE id = ? AND status = 'sending'
                """,
                (now, target.id),
            )
            await db.execute(
                """
                UPDATE chat_group_members SET last_broadcast_at = ?
                WHERE chat_id = ?
                """,
                (now, target.chat_id),
            )
            await db.commit()

    async def target_failed(
        self,
        target: TargetRecord,
        *,
        status: str,
        error_code: str,
        error_message: str,
        deactivate: bool = False,
    ) -> None:
        """Зафиксировать ошибку одного таргета, не останавливая рассылку."""
        safe_message = error_message[:500]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE broadcast_targets
                SET status = ?, error_code = ?, error_message = ?
                WHERE id = ? AND status = 'sending'
                """,
                (status, error_code, safe_message, target.id),
            )
            if deactivate:
                await db.execute(
                    """
                    UPDATE chat_group_members
                    SET is_active = 0, deactivated_reason = ?
                    WHERE chat_id = ?
                    """,
                    (error_code, target.chat_id),
                )
            await db.commit()

    async def was_sent_recently(self, chat_id: str, cutoff_iso: str) -> bool:
        """Проверить консервативный межкампанийный кулдаун чата."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT 1 FROM chat_group_members
                WHERE chat_id = ? AND last_broadcast_at IS NOT NULL
                  AND last_broadcast_at > ?
                LIMIT 1
                """,
                (chat_id, cutoff_iso),
            )
            return await cursor.fetchone() is not None

    async def migrate_chat(self, target: TargetRecord, new_chat_id: int) -> TargetRecord:
        """Обновить идентификатор мигрировавшей группы и текущий таргет."""
        new_value = str(new_chat_id)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE chat_group_members SET chat_id = ? WHERE chat_id = ?",
                (new_value, target.chat_id),
            )
            await db.execute(
                "UPDATE broadcast_targets SET chat_id = ? WHERE id = ?",
                (new_value, target.id),
            )
            await db.commit()
        return TargetRecord(target.id, target.broadcast_id, new_value, target.attempts)

    async def status(self, broadcast_id: int) -> Optional[str]:
        """Вернуть текущий управляющий статус рассылки."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT status FROM broadcasts WHERE id = ?", (broadcast_id,)
            )
            row = await cursor.fetchone()
        return str(row[0]) if row else None

    async def set_status(self, broadcast_id: int, status: str) -> bool:
        """Изменить статус для паузы, возобновления или отмены."""
        allowed = {
            "paused": ("queued", "running"),
            "queued": ("paused",),
            "cancelled": ("queued", "running", "paused"),
        }
        previous = allowed.get(status)
        if previous is None:
            raise ValueError(f"Unsupported broadcast status transition: {status}")
        placeholders = ",".join("?" for _ in previous)
        params: list[object] = [status]
        sql = "UPDATE broadcasts SET status = ?"
        if status == "cancelled":
            sql += ", finished_at = ?"
            params.append(utcnow_iso())
        sql += f" WHERE id = ? AND status IN ({placeholders})"
        params.extend([broadcast_id, *previous])
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(sql, params)
            if status == "cancelled" and cursor.rowcount:
                await db.execute(
                    """
                    UPDATE broadcast_targets
                    SET status = 'skipped', error_code = 'cancelled'
                    WHERE broadcast_id = ? AND status = 'pending'
                    """,
                    (broadcast_id,),
                )
            await db.commit()
        return cursor.rowcount > 0

    async def counts(self, broadcast_id: int) -> dict[str, int]:
        """Посчитать таргеты непосредственно по их статусам."""
        result = {name: 0 for name in ("pending", "sending", "sent", "failed", "blocked", "skipped")}
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT status, COUNT(*) FROM broadcast_targets
                WHERE broadcast_id = ? GROUP BY status
                """,
                (broadcast_id,),
            )
            for status, count in await cursor.fetchall():
                result[str(status)] = int(count)
        result["total"] = sum(result.values())
        return result

    async def sync_counts(self, broadcast_id: int) -> dict[str, int]:
        """Синхронизировать агрегаты карточки с таблицей таргетов."""
        counts = await self.counts(broadcast_id)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE broadcasts
                SET total_count = ?, sent_count = ?, failed_count = ?,
                    blocked_count = ?, skipped_count = ?
                WHERE id = ?
                """,
                (
                    counts["total"],
                    counts["sent"],
                    counts["failed"],
                    counts["blocked"],
                    counts["skipped"],
                    broadcast_id,
                ),
            )
            await db.commit()
        return counts

    async def finish(self, broadcast_id: int) -> dict[str, int]:
        """Завершить рассылку, если все таргеты получили конечный статус."""
        counts = await self.sync_counts(broadcast_id)
        if counts["pending"] or counts["sending"]:
            return counts
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE broadcasts SET status = 'done', finished_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (utcnow_iso(), broadcast_id),
            )
            await db.commit()
        return counts

    async def fail_broadcast(self, broadcast_id: int, error: str) -> None:
        """Завершить повреждённую рассылку с диагностикой."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE broadcasts
                SET status = 'failed', finished_at = ?, last_error = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (utcnow_iso(), error[:500], broadcast_id),
            )
            await db.execute(
                """
                UPDATE broadcast_targets
                SET status = 'skipped', error_code = 'broadcast_failed'
                WHERE broadcast_id = ? AND status = 'pending'
                """,
                (broadcast_id,),
            )
            await db.commit()
