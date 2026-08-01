"""Хранилище PostgreSQL-очереди и разрешённых чатов рассылки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db import get_session_factory
from core.models import (
    BroadcastCampaign,
    BroadcastGroup,
    BroadcastRecipient,
    BroadcastStatus,
    BroadcastTarget,
    BroadcastTargetStatus,
)


def utcnow() -> datetime:
    """Вернуть naive UTC для единообразного хранения в PostgreSQL/SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class GroupRecord:
    """Сохранённый ручной сегмент чатов."""

    id: int
    owner_telegram_id: int
    name: str
    created_at: datetime


@dataclass(frozen=True)
class RecipientRecord:
    """Разрешённый чат внутри сегмента."""

    id: int
    group_id: int
    chat_id: int
    chat_type: str
    title: Optional[str]
    username: Optional[str]
    language_code: Optional[str]
    is_active: bool


@dataclass(frozen=True)
class BroadcastRecord:
    """Кампания, готовая к исполнению."""

    id: int
    owner_telegram_id: int
    group_id: int
    status: str
    content_type: str
    source_chat_id: int
    source_message_ids: tuple[int, ...]
    reply_markup: Optional[list[list[dict[str, str]]]]
    filters: dict[str, Any]
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    progress_chat_id: Optional[int]
    progress_message_id: Optional[int]
    disable_notification: bool
    protect_content: bool


@dataclass(frozen=True)
class TargetRecord:
    """Один получатель неизменяемого снимка аудитории."""

    id: int
    broadcast_id: int
    chat_id: int
    attempts: int


class BroadcastRepository:
    """Транзакционные операции над очередью рассылок."""

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()

    async def create_group(self, owner_telegram_id: int, name: str) -> int:
        """Создать ручной сегмент чатов."""
        async with self.session_factory() as session:
            group = BroadcastGroup(owner_telegram_id=owner_telegram_id, name=name)
            session.add(group)
            await session.commit()
            await session.refresh(group)
            return group.id

    async def list_groups(self, owner_telegram_id: int) -> list[GroupRecord]:
        """Вернуть сегменты владельца."""
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(BroadcastGroup)
                .where(BroadcastGroup.owner_telegram_id == owner_telegram_id)
                .order_by(BroadcastGroup.created_at.desc())
            )
            return [self._group_record(row) for row in rows]

    async def get_group(
        self, group_id: int, owner_telegram_id: Optional[int] = None
    ) -> Optional[GroupRecord]:
        """Найти сегмент с опциональной проверкой владельца."""
        statement = select(BroadcastGroup).where(BroadcastGroup.id == group_id)
        if owner_telegram_id is not None:
            statement = statement.where(
                BroadcastGroup.owner_telegram_id == owner_telegram_id
            )
        async with self.session_factory() as session:
            group = await session.scalar(statement)
            return self._group_record(group) if group else None

    async def delete_group(self, group_id: int, owner_telegram_id: int) -> bool:
        """Удалить сегмент без доступа к чужим данным."""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(BroadcastGroup).where(
                    BroadcastGroup.id == group_id,
                    BroadcastGroup.owner_telegram_id == owner_telegram_id,
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def add_recipient(
        self,
        *,
        group_id: int,
        owner_telegram_id: int,
        chat_id: int,
        chat_type: str,
        title: Optional[str],
        username: Optional[str],
        language_code: Optional[str],
    ) -> bool:
        """Добавить или реактивировать проверенный чат."""
        async with self.session_factory() as session:
            group_exists = await session.scalar(
                select(BroadcastGroup.id).where(
                    BroadcastGroup.id == group_id,
                    BroadcastGroup.owner_telegram_id == owner_telegram_id,
                )
            )
            if group_exists is None:
                return False
            recipient = await session.scalar(
                select(BroadcastRecipient).where(
                    BroadcastRecipient.group_id == group_id,
                    BroadcastRecipient.chat_id == chat_id,
                )
            )
            if recipient is None:
                recipient = BroadcastRecipient(group_id=group_id, chat_id=chat_id)
                session.add(recipient)
            recipient.chat_type = chat_type
            recipient.title = title
            recipient.username = username
            recipient.language_code = language_code
            recipient.is_active = True
            recipient.deactivated_reason = None
            await session.commit()
            return True

    async def list_recipients(self, group_id: int) -> list[RecipientRecord]:
        """Вернуть активных членов сегмента."""
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(BroadcastRecipient).where(
                    BroadcastRecipient.group_id == group_id,
                    BroadcastRecipient.is_active.is_(True),
                )
            )
            return [self._recipient_record(row) for row in rows]

    async def count_recipients(self, group_id: int, filters: dict[str, Any]) -> int:
        """Посчитать активную аудиторию по фильтрам."""
        statement = select(func.count(BroadcastRecipient.id)).where(
            *self._audience_conditions(group_id, filters)
        )
        async with self.session_factory() as session:
            return int((await session.scalar(statement)) or 0)

    async def create_broadcast(
        self,
        *,
        owner_telegram_id: int,
        group_id: int,
        source_chat_id: int,
        source_message_ids: list[int],
        content_type: str,
        reply_markup: Optional[list[list[dict[str, str]]]],
        filters: dict[str, Any],
        progress_chat_id: int,
        progress_message_id: int,
        scheduled_at: Optional[datetime] = None,
        disable_notification: bool = False,
        protect_content: bool = False,
    ) -> tuple[int, int]:
        """Создать кампанию и её неизменяемый снимок аудитории."""
        if not source_message_ids:
            raise ValueError("Broadcast source is empty")
        async with self.session_factory() as session:
            group_exists = await session.scalar(
                select(BroadcastGroup.id).where(
                    BroadcastGroup.id == group_id,
                    BroadcastGroup.owner_telegram_id == owner_telegram_id,
                )
            )
            if group_exists is None:
                raise ValueError("Broadcast group not found")
            campaign = BroadcastCampaign(
                owner_telegram_id=owner_telegram_id,
                group_id=group_id,
                content_type=content_type,
                source_chat_id=source_chat_id,
                source_message_ids=source_message_ids,
                reply_markup=reply_markup,
                filters=filters,
                progress_chat_id=progress_chat_id,
                progress_message_id=progress_message_id,
                scheduled_at=self._naive_utc(scheduled_at),
                disable_notification=disable_notification,
                protect_content=protect_content,
            )
            session.add(campaign)
            await session.flush()
            chat_ids = list(
                await session.scalars(
                    select(BroadcastRecipient.chat_id).where(
                        *self._audience_conditions(group_id, filters)
                    )
                )
            )
            session.add_all(
                BroadcastTarget(broadcast_id=campaign.id, chat_id=chat_id)
                for chat_id in dict.fromkeys(chat_ids)
            )
            campaign.total_count = len(set(chat_ids))
            await session.commit()
            return campaign.id, campaign.total_count

    async def recover_uncertain_targets(self) -> int:
        """Не повторять таргеты, которые могли уйти до аварии."""
        async with self.session_factory() as session:
            result = await session.execute(
                update(BroadcastTarget)
                .where(BroadcastTarget.status == BroadcastTargetStatus.SENDING)
                .values(
                    status=BroadcastTargetStatus.SKIPPED,
                    error_code="uncertain_after_restart",
                    error_message="Не повторено после перезапуска во избежание дубля",
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def due_broadcast_ids(self, limit: int = 10) -> list[int]:
        """Вернуть готовые к запуску кампании."""
        now = utcnow()
        async with self.session_factory() as session:
            values = await session.scalars(
                select(BroadcastCampaign.id)
                .where(
                    BroadcastCampaign.status.in_(
                        (BroadcastStatus.QUEUED, BroadcastStatus.RUNNING)
                    ),
                    (BroadcastCampaign.scheduled_at.is_(None))
                    | (BroadcastCampaign.scheduled_at <= now),
                )
                .order_by(BroadcastCampaign.created_at)
                .limit(limit)
            )
            return list(values)

    async def get_broadcast(self, broadcast_id: int) -> Optional[BroadcastRecord]:
        """Загрузить кампанию."""
        async with self.session_factory() as session:
            campaign = await session.get(BroadcastCampaign, broadcast_id)
            return self._broadcast_record(campaign) if campaign else None

    async def start(self, broadcast_id: int) -> bool:
        """Атомарно перевести кампанию в running."""
        async with self.session_factory() as session:
            result = await session.execute(
                update(BroadcastCampaign)
                .where(
                    BroadcastCampaign.id == broadcast_id,
                    BroadcastCampaign.status.in_(
                        (BroadcastStatus.QUEUED, BroadcastStatus.RUNNING)
                    ),
                )
                .values(
                    status=BroadcastStatus.RUNNING,
                    started_at=func.coalesce(BroadcastCampaign.started_at, utcnow()),
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def claim_targets(self, broadcast_id: int, limit: int) -> list[TargetRecord]:
        """Зарезервировать батч через SELECT FOR UPDATE SKIP LOCKED."""
        async with self.session_factory() as session:
            rows = list(
                await session.scalars(
                    select(BroadcastTarget)
                    .where(
                        BroadcastTarget.broadcast_id == broadcast_id,
                        BroadcastTarget.status == BroadcastTargetStatus.PENDING,
                    )
                    .order_by(BroadcastTarget.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            claimed_at = utcnow()
            for row in rows:
                row.status = BroadcastTargetStatus.SENDING
                row.attempts += 1
                row.claimed_at = claimed_at
            await session.commit()
            return [self._target_record(row) for row in rows]

    async def increment_attempts(self, target_id: int) -> int:
        """Учесть дополнительную попытку."""
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastTarget)
                .where(BroadcastTarget.id == target_id)
                .values(attempts=BroadcastTarget.attempts + 1)
            )
            await session.commit()
            value = await session.scalar(
                select(BroadcastTarget.attempts).where(BroadcastTarget.id == target_id)
            )
            return int(value or 0)

    async def target_succeeded(self, target: TargetRecord) -> None:
        """Зафиксировать доставку и кулдаун чата."""
        now = utcnow()
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastTarget)
                .where(
                    BroadcastTarget.id == target.id,
                    BroadcastTarget.status == BroadcastTargetStatus.SENDING,
                )
                .values(
                    status=BroadcastTargetStatus.SENT,
                    sent_at=now,
                    error_code=None,
                    error_message=None,
                )
            )
            await session.execute(
                update(BroadcastRecipient)
                .where(BroadcastRecipient.chat_id == target.chat_id)
                .values(last_broadcast_at=now)
            )
            await session.commit()

    async def target_failed(
        self,
        target: TargetRecord,
        *,
        status: str,
        error_code: str,
        error_message: str,
        deactivate: bool = False,
    ) -> None:
        """Зафиксировать ошибку, не останавливая кампанию."""
        target_status = BroadcastTargetStatus(status)
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastTarget)
                .where(
                    BroadcastTarget.id == target.id,
                    BroadcastTarget.status == BroadcastTargetStatus.SENDING,
                )
                .values(
                    status=target_status,
                    error_code=error_code,
                    error_message=error_message[:500],
                )
            )
            if deactivate:
                await session.execute(
                    update(BroadcastRecipient)
                    .where(BroadcastRecipient.chat_id == target.chat_id)
                    .values(is_active=False, deactivated_reason=error_code)
                )
            await session.commit()

    async def was_sent_recently(self, chat_id: int, cutoff: datetime) -> bool:
        """Проверить межкампанийный кулдаун."""
        async with self.session_factory() as session:
            value = await session.scalar(
                select(BroadcastRecipient.id)
                .where(
                    BroadcastRecipient.chat_id == chat_id,
                    BroadcastRecipient.last_broadcast_at.is_not(None),
                    BroadcastRecipient.last_broadcast_at > self._naive_utc(cutoff),
                )
                .limit(1)
            )
            return value is not None

    async def migrate_chat(
        self, target: TargetRecord, new_chat_id: int
    ) -> TargetRecord:
        """Обновить chat_id после миграции группы."""
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastTarget)
                .where(BroadcastTarget.id == target.id)
                .values(chat_id=new_chat_id)
            )
            old_rows = list(
                await session.scalars(
                    select(BroadcastRecipient).where(
                        BroadcastRecipient.chat_id == target.chat_id
                    )
                )
            )
            for old in old_rows:
                existing = await session.scalar(
                    select(BroadcastRecipient.id).where(
                        BroadcastRecipient.group_id == old.group_id,
                        BroadcastRecipient.chat_id == new_chat_id,
                    )
                )
                if existing is None:
                    old.chat_id = new_chat_id
                else:
                    await session.delete(old)
            await session.commit()
        return TargetRecord(
            target.id, target.broadcast_id, new_chat_id, target.attempts
        )

    async def status(self, broadcast_id: int) -> Optional[str]:
        """Вернуть текущий статус."""
        async with self.session_factory() as session:
            value = await session.scalar(
                select(BroadcastCampaign.status).where(
                    BroadcastCampaign.id == broadcast_id
                )
            )
            return value.value if value else None

    async def set_status(self, broadcast_id: int, status: str) -> bool:
        """Пауза, возобновление или отмена кампании."""
        allowed: dict[str, tuple[BroadcastStatus, ...]] = {
            "paused": (BroadcastStatus.QUEUED, BroadcastStatus.RUNNING),
            "queued": (BroadcastStatus.PAUSED,),
            "cancelled": (
                BroadcastStatus.QUEUED,
                BroadcastStatus.RUNNING,
                BroadcastStatus.PAUSED,
            ),
        }
        previous = allowed.get(status)
        if previous is None:
            raise ValueError(f"Unsupported broadcast status transition: {status}")
        values: dict[str, Any] = {"status": BroadcastStatus(status)}
        if status == "cancelled":
            values["finished_at"] = utcnow()
        async with self.session_factory() as session:
            result = await session.execute(
                update(BroadcastCampaign)
                .where(
                    BroadcastCampaign.id == broadcast_id,
                    BroadcastCampaign.status.in_(previous),
                )
                .values(**values)
            )
            if status == "cancelled" and result.rowcount:
                await session.execute(
                    update(BroadcastTarget)
                    .where(
                        BroadcastTarget.broadcast_id == broadcast_id,
                        BroadcastTarget.status == BroadcastTargetStatus.PENDING,
                    )
                    .values(
                        status=BroadcastTargetStatus.SKIPPED,
                        error_code="cancelled",
                    )
                )
            await session.commit()
            return bool(result.rowcount)

    async def counts(self, broadcast_id: int) -> dict[str, int]:
        """Посчитать таргеты непосредственно по статусам."""
        result = {
            name: 0
            for name in ("pending", "sending", "sent", "failed", "blocked", "skipped")
        }
        async with self.session_factory() as session:
            rows = await session.execute(
                select(BroadcastTarget.status, func.count(BroadcastTarget.id))
                .where(BroadcastTarget.broadcast_id == broadcast_id)
                .group_by(BroadcastTarget.status)
            )
            for status, count in rows:
                result[status.value] = int(count)
        result["total"] = sum(result.values())
        return result

    async def sync_counts(self, broadcast_id: int) -> dict[str, int]:
        """Синхронизировать агрегаты кампании."""
        counts = await self.counts(broadcast_id)
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastCampaign)
                .where(BroadcastCampaign.id == broadcast_id)
                .values(
                    total_count=counts["total"],
                    sent_count=counts["sent"],
                    failed_count=counts["failed"],
                    blocked_count=counts["blocked"],
                    skipped_count=counts["skipped"],
                )
            )
            await session.commit()
        return counts

    async def finish(self, broadcast_id: int) -> dict[str, int]:
        """Завершить исчерпанную кампанию."""
        counts = await self.sync_counts(broadcast_id)
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastCampaign)
                .where(
                    BroadcastCampaign.id == broadcast_id,
                    BroadcastCampaign.status == BroadcastStatus.RUNNING,
                )
                .values(status=BroadcastStatus.DONE, finished_at=utcnow())
            )
            await session.commit()
        return counts

    async def fail_broadcast(self, broadcast_id: int, error: str) -> None:
        """Завершить повреждённую кампанию."""
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastCampaign)
                .where(
                    BroadcastCampaign.id == broadcast_id,
                    BroadcastCampaign.status.in_(
                        (BroadcastStatus.QUEUED, BroadcastStatus.RUNNING)
                    ),
                )
                .values(
                    status=BroadcastStatus.FAILED,
                    finished_at=utcnow(),
                    last_error=error[:500],
                )
            )
            await session.execute(
                update(BroadcastTarget)
                .where(
                    BroadcastTarget.broadcast_id == broadcast_id,
                    BroadcastTarget.status == BroadcastTargetStatus.PENDING,
                )
                .values(
                    status=BroadcastTargetStatus.SKIPPED,
                    error_code="broadcast_failed",
                )
            )
            await session.commit()

    async def set_progress_message(self, broadcast_id: int, message_id: int) -> None:
        """Сохранить ID сообщения прогресса."""
        async with self.session_factory() as session:
            await session.execute(
                update(BroadcastCampaign)
                .where(BroadcastCampaign.id == broadcast_id)
                .values(progress_message_id=message_id)
            )
            await session.commit()

    async def history(
        self, owner_telegram_id: int, limit: int = 20
    ) -> list[BroadcastCampaign]:
        """Вернуть последние кампании владельца."""
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(BroadcastCampaign)
                .where(BroadcastCampaign.owner_telegram_id == owner_telegram_id)
                .order_by(BroadcastCampaign.created_at.desc())
                .limit(limit)
            )
            return list(rows)

    @staticmethod
    def _audience_conditions(group_id: int, filters: dict[str, Any]) -> list[Any]:
        conditions: list[Any] = [
            BroadcastRecipient.group_id == group_id,
            BroadcastRecipient.is_active.is_(True),
        ]
        chat_types = filters.get("chat_types") or []
        if chat_types:
            conditions.append(BroadcastRecipient.chat_type.in_(chat_types))
        languages = [str(value).casefold() for value in filters.get("languages") or []]
        if languages:
            conditions.append(
                func.lower(BroadcastRecipient.language_code).in_(languages)
            )
        return conditions

    @staticmethod
    def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _group_record(group: BroadcastGroup) -> GroupRecord:
        return GroupRecord(
            group.id, group.owner_telegram_id, group.name, group.created_at
        )

    @staticmethod
    def _recipient_record(recipient: BroadcastRecipient) -> RecipientRecord:
        return RecipientRecord(
            recipient.id,
            recipient.group_id,
            recipient.chat_id,
            recipient.chat_type,
            recipient.title,
            recipient.username,
            recipient.language_code,
            recipient.is_active,
        )

    @staticmethod
    def _target_record(target: BroadcastTarget) -> TargetRecord:
        return TargetRecord(
            target.id, target.broadcast_id, target.chat_id, target.attempts
        )

    @staticmethod
    def _broadcast_record(campaign: BroadcastCampaign) -> BroadcastRecord:
        markup = campaign.reply_markup
        return BroadcastRecord(
            id=campaign.id,
            owner_telegram_id=campaign.owner_telegram_id,
            group_id=campaign.group_id,
            status=campaign.status.value,
            content_type=campaign.content_type,
            source_chat_id=campaign.source_chat_id,
            source_message_ids=tuple(
                int(value) for value in campaign.source_message_ids
            ),
            reply_markup=markup,
            filters=dict(campaign.filters or {}),
            scheduled_at=campaign.scheduled_at,
            started_at=campaign.started_at,
            progress_chat_id=campaign.progress_chat_id,
            progress_message_id=campaign.progress_message_id,
            disable_notification=campaign.disable_notification,
            protect_content=campaign.protect_content,
        )
