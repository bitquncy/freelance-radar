"""Unit tests for AI cache."""
import pytest
import asyncio
from services.ai_cache import AICache


class TestAICache:
    @pytest.fixture
    def cache(self):
        return AICache(maxsize=3, ttl_seconds=1)

    @pytest.mark.asyncio
    async def test_cache_miss(self, cache):
        """Test cache miss returns None."""
        result = await cache.get("123", {"title": "test", "description": "desc"})
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit(self, cache):
        """Test cache hit returns stored result."""
        vacancy_data = {"title": "test", "description": "desc"}
        expected = {"score": 75, "priority": "high"}
        await cache.set("123", vacancy_data, expected)
        result = await cache.get("123", vacancy_data)
        assert result == expected

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self, cache):
        """Test that expired entries are evicted."""
        vacancy_data = {"title": "test", "description": "desc"}
        await cache.set("123", vacancy_data, {"score": 50})
        await asyncio.sleep(1.1)
        result = await cache.get("123", vacancy_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self, cache):
        """Test LRU eviction when maxsize is reached."""
        for i in range(4):
            await cache.set(str(i), {"title": f"t{i}"}, {"score": i})

        # Oldest (0) should be evicted
        result = await cache.get("0", {"title": "t0"})
        assert result is None

        # Newer entries should still exist
        result = await cache.get("3", {"title": "t3"})
        assert result == {"score": 3}

    @pytest.mark.asyncio
    async def test_cache_invalidate(self, cache):
        """Test invalidation by kwork_id — only exact match, not prefix."""
        await cache.set("abc", {"title": "t1"}, {"score": 1})
        await cache.set("abc2", {"title": "t2"}, {"score": 2})
        await cache.set("xyz", {"title": "t3"}, {"score": 3})

        await cache.invalidate("abc")

        # Exact match invalidated
        assert await cache.get("abc", {"title": "t1"}) is None
        # Different id with similar prefix should remain
        assert await cache.get("abc2", {"title": "t2"}) is not None
        # Completely different id should remain
        assert await cache.get("xyz", {"title": "t3"}) is not None

    @pytest.mark.asyncio
    async def test_cache_stats(self, cache):
        """Test cache statistics."""
        await cache.set("1", {"title": "t1"}, {"score": 1})
        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["maxsize"] == 3
        assert stats["ttl_seconds"] == 1

    @pytest.mark.asyncio
    async def test_cache_content_change(self, cache):
        """Test that changing vacancy content invalidates cache."""
        await cache.set("123", {"title": "old", "description": "old desc"}, {"score": 50})
        # Same id but different content -> cache miss
        result = await cache.get("123", {"title": "new", "description": "new desc"})
        assert result is None
