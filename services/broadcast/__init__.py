"""Безопасная очередь рассылок по явно разрешённым Telegram-чатам."""

from services.broadcast.repository import BroadcastRecord, BroadcastRepository, TargetRecord
from services.broadcast.runner import BroadcastRunner

__all__ = ["BroadcastRecord", "BroadcastRepository", "BroadcastRunner", "TargetRecord"]
