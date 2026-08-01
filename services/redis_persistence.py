"""Redis persistence for python-telegram-bot conversations and user_data."""

from __future__ import annotations

import json
from typing import Any, MutableMapping, Optional

from redis.asyncio import Redis
from telegram.ext import BasePersistence, PersistenceInput


class RedisPersistence(BasePersistence[dict, dict, dict]):
    """Store FSM state in Redis without executable pickle payloads."""

    def __init__(self, redis_url: str, prefix: str = "freelance-radar:ptb") -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=False,
                user_data=True,
                callback_data=False,
            ),
            update_interval=1,
        )
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.prefix = prefix

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}:{suffix}"

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load(value: str) -> Any:
        return json.loads(value)

    async def get_user_data(self) -> dict[int, dict]:
        values = await self.redis.hgetall(self._key("user_data"))
        return {int(key): dict(self._load(value)) for key, value in values.items()}

    async def update_user_data(self, user_id: int, data: dict) -> None:
        await self.redis.hset(self._key("user_data"), str(user_id), self._dump(data))

    async def drop_user_data(self, user_id: int) -> None:
        await self.redis.hdel(self._key("user_data"), str(user_id))

    async def refresh_user_data(self, user_id: int, user_data: dict) -> None:
        return None

    async def get_chat_data(self) -> dict[int, dict]:
        return {}

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        return None

    async def drop_chat_data(self, chat_id: int) -> None:
        return None

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> None:
        return None

    async def get_bot_data(self) -> dict:
        return {}

    async def update_bot_data(self, data: dict) -> None:
        return None

    async def refresh_bot_data(self, bot_data: dict) -> None:
        return None

    async def get_callback_data(self) -> None:
        return None

    async def update_callback_data(self, data: object) -> None:
        return None

    async def get_conversations(
        self, name: str
    ) -> MutableMapping[tuple[int | str, ...], object]:
        values = await self.redis.hgetall(self._key(f"conversation:{name}"))
        result: dict[tuple[int | str, ...], object] = {}
        for encoded_key, encoded_state in values.items():
            key = tuple(self._load(encoded_key))
            result[key] = self._load(encoded_state)
        return result

    async def update_conversation(
        self,
        name: str,
        key: tuple[int | str, ...],
        new_state: Optional[object],
    ) -> None:
        redis_key = self._key(f"conversation:{name}")
        encoded_key = self._dump(list(key))
        if new_state is None:
            await self.redis.hdel(redis_key, encoded_key)
            return
        await self.redis.hset(redis_key, encoded_key, self._dump(new_state))

    async def flush(self) -> None:
        await self.redis.aclose()
