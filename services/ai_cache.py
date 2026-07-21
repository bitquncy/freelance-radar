"""In-memory LRU cache for OpenAI analysis results with TTL."""
import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from services.logger_config import get_logger

logger = get_logger(__name__)


class AICache:
    """Thread-safe LRU cache with TTL for AI analysis results.

    Cache key is derived from vacancy data (kwork_id + content hash).
    This avoids re-analyzing identical vacancies across check cycles.
    """

    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 86400):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._timestamps: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _make_key(self, kwork_id: str, vacancy_data: Dict[str, Any]) -> str:
        """Create deterministic cache key from vacancy identity."""
        # Use kwork_id + hash of title/description for content-based invalidation
        content = json.dumps({
            "id": kwork_id,
            "title": vacancy_data.get("title", ""),
            "description": vacancy_data.get("description", "")[:200],
            "budget": vacancy_data.get("budget"),
        }, sort_keys=True, ensure_ascii=False)
        digest = hashlib.md5(content.encode("utf-8")).hexdigest()[:16]
        return f"ai:{kwork_id}--{digest}"

    async def get(self, kwork_id: str, vacancy_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached analysis result if present and not expired."""
        key = self._make_key(kwork_id, vacancy_data)
        async with self._lock:
            now = time.time()
            if key in self._cache:
                if now - self._timestamps[key] <= self.ttl_seconds:
                    # Move to end (most recently used)
                    self._cache.move_to_end(key)
                    logger.debug("ai_cache.hit", key=key[:30])
                    return self._cache[key]
                else:
                    # Expired
                    self._evict(key)
                    logger.debug("ai_cache.expired", key=key[:30])
            return None

    async def set(self, kwork_id: str, vacancy_data: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Cache analysis result."""
        key = self._make_key(kwork_id, vacancy_data)
        async with self._lock:
            # Evict oldest if at capacity
            while len(self._cache) >= self.maxsize:
                oldest_key, _ = self._cache.popitem(last=False)
                self._timestamps.pop(oldest_key, None)

            self._cache[key] = result
            self._timestamps[key] = time.time()
            logger.debug("ai_cache.set", key=key[:30], size=len(self._cache))

    def _evict(self, key: str) -> None:
        """Remove entry from cache."""
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)

    async def invalidate(self, kwork_id: str) -> None:
        """Invalidate all entries for a given kwork_id prefix."""
        async with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(f"ai:{kwork_id}--")]
            for key in keys_to_remove:
                self._evict(key)
            logger.info("ai_cache.invalidated", kwork_id=kwork_id, count=len(keys_to_remove))

    async def clear(self) -> None:
        """Clear entire cache."""
        async with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            logger.info("ai_cache.cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        now = time.time()
        expired = sum(1 for ts in self._timestamps.values() if now - ts > self.ttl_seconds)
        return {
            "size": len(self._cache),
            "maxsize": self.maxsize,
            "ttl_seconds": self.ttl_seconds,
            "expired_entries": expired,
        }


# Global cache instance
_ai_cache: Optional[AICache] = None


def get_ai_cache() -> AICache:
    """Get or create global AI cache instance."""
    global _ai_cache
    if _ai_cache is None:
        _ai_cache = AICache()
    return _ai_cache
