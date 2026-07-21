"""Unit tests for DI container (ServiceRegistry)."""
import pytest
from services.dependencies import ServiceRegistry


class TestServiceRegistry:
    @pytest.fixture
    def registry(self):
        return ServiceRegistry()

    def test_register_singleton(self, registry):
        """Test singleton registration and retrieval."""
        registry.register_singleton("test_service", lambda: {"value": 42})
        result = registry.get("test_service")
        assert result == {"value": 42}

    def test_singleton_returns_same_instance(self, registry):
        """Test that singletons return the same instance."""
        registry.register_singleton("test_service", lambda: {"value": 42})
        result1 = registry.get("test_service")
        result2 = registry.get("test_service")
        assert result1 is result2

    def test_register_factory(self, registry):
        """Test factory registration and retrieval."""
        registry.register_factory("test_service", lambda: {"value": 42})
        result1 = registry.get("test_service")
        result2 = registry.get("test_service")
        assert result1 == result2
        assert result1 is not result2  # Different instances

    def test_override(self, registry):
        """Test overriding a service."""
        registry.register_singleton("test_service", lambda: {"value": 42})
        registry.override("test_service", {"value": 99})
        result = registry.get("test_service")
        assert result == {"value": 99}

    def test_get_optional(self, registry):
        """Test optional service retrieval."""
        result = registry.get_optional("nonexistent", default={"value": 0})
        assert result == {"value": 0}

    def test_has(self, registry):
        """Test service existence check."""
        registry.register_singleton("test_service", lambda: {"value": 42})
        assert registry.has("test_service")
        assert not registry.has("nonexistent")

    def test_reset(self, registry):
        """Test registry reset."""
        registry.register_singleton("test_service", lambda: {"value": 42})
        registry.reset()
        assert not registry.has("test_service")

    def test_get_stats(self, registry):
        """Test registry statistics."""
        registry.register_singleton("test_singleton", lambda: {})
        registry.register_factory("test_factory", lambda: {})
        stats = registry.get_stats()
        assert stats["singletons"] == 1
        assert stats["factories"] == 1

    def test_key_error_for_missing(self, registry):
        """Test that KeyError is raised for missing service."""
        with pytest.raises(KeyError):
            registry.get("nonexistent")
