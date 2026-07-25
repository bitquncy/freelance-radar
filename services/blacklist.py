"""Blacklist service for managing blocked vacancies and customers."""
from datetime import datetime, timedelta
from typing import List, Optional

import aiosqlite

from db.models import Blacklist
from db import queries
from services.logger_config import get_logger

logger = get_logger(__name__)


class BlacklistService:
    """Service for managing blacklisted entities (vacancies and customers)."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def is_blacklisted(self, entity_type: str, entity_id: str) -> bool:
        """Check if an entity is in the blacklist.

        Args:
            entity_type: 'vacancy' or 'customer'
            entity_id: kwork_id or customer identifier

        Returns:
            True if entity is blacklisted and not expired, False otherwise.
            An uninitialized database (missing table) degrades to False —
            filtering must not crash the monitoring pipeline.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                result = await queries.is_blacklisted(db, entity_type, entity_id)
        except aiosqlite.OperationalError as exc:
            logger.warning(
                "blacklist.check_degraded",
                entity_type=entity_type,
                entity_id=entity_id,
                error=str(exc),
            )
            return False
        logger.debug(
            "blacklist.checked",
            entity_type=entity_type,
            entity_id=entity_id,
            is_blacklisted=result,
        )
        return result

    async def add_to_blacklist(
        self,
        entity_type: str,
        entity_id: str,
        user_id: int,
        reason: Optional[str] = None,
        ttl_days: Optional[int] = None,
    ) -> None:
        """Add an entity to the blacklist.

        Args:
            entity_type: 'vacancy' or 'customer'
            entity_id: kwork_id or customer identifier
            user_id: ID of the user who added the entry
            reason: Optional reason for blacklisting
            ttl_days: Optional TTL in days (None = permanent)
        """
        expires_at = None
        if ttl_days is not None:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await queries.add_to_blacklist(
                db, entity_type, entity_id, user_id, reason, expires_at
            )
        logger.info(
            "blacklist.added",
            entity_type=entity_type,
            entity_id=entity_id,
            reason=reason,
            ttl_days=ttl_days,
        )

    async def remove_from_blacklist(self, entity_type: str, entity_id: str) -> None:
        """Remove an entity from the blacklist.

        Args:
            entity_type: 'vacancy' or 'customer'
            entity_id: kwork_id or customer identifier
        """
        async with aiosqlite.connect(self.db_path) as db:
            await queries.remove_from_blacklist(db, entity_type, entity_id)
        logger.info(
            "blacklist.removed",
            entity_type=entity_type,
            entity_id=entity_id,
        )

    async def get_blacklist(
        self, entity_type: Optional[str] = None
    ) -> List[Blacklist]:
        """Get all blacklist entries, optionally filtered by entity_type.

        Args:
            entity_type: 'vacancy' or 'customer', or None for all

        Returns:
            List of Blacklist entries (excluding expired ones).
        """
        async with aiosqlite.connect(self.db_path) as db:
            entries = await queries.get_blacklist(db, entity_type)
        logger.info(
            "blacklist.listed",
            count=len(entries),
            entity_type=entity_type,
        )
        return entries

    async def check_vacancy(self, kwork_id: str, customer_id: Optional[str] = None) -> bool:
        """Check if a vacancy or its customer is blacklisted.

        Args:
            kwork_id: The vacancy ID
            customer_id: Optional customer identifier

        Returns:
            True if vacancy or customer is blacklisted and not expired.
        """
        if await self.is_blacklisted("vacancy", kwork_id):
            return True
        if customer_id and await self.is_blacklisted("customer", customer_id):
            return True
        return False

    async def cleanup_expired(self) -> int:
        """Remove expired blacklist entries.

        Returns:
            Number of expired entries removed.
        """
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM blacklist WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,)
            )
            removed = cursor.rowcount
            await db.commit()
        if removed > 0:
            logger.info("blacklist.expired_removed", count=removed)
        return removed
