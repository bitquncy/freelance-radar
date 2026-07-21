"""Dependency injection container for FreelanceRadar bot."""
from typing import Any, Dict, Optional, TypeVar

from services.logger_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class ServiceRegistry:
    """Simple dependency injection container with singleton support.

    Usage:
        registry = ServiceRegistry()

        # Register a service with lazy initialization
        registry.register_singleton("job_analyzer", JobAnalyzer)

        # Get instance (created on first access)
        analyzer = registry.get("job_analyzer")

        # Register a factory (new instance each time)
        registry.register_factory("vacancy_filter", lambda: VacancyFilter(profile))

        # Override for testing
        registry.override("job_analyzer", mock_analyzer)
    """

    def __init__(self):
        self._singletons: Dict[str, Any] = {}
        self._factories: Dict[str, callable] = {}
        self._overrides: Dict[str, Any] = {}
        self._initialized = False

    def register_singleton(self, name: str, factory: callable) -> None:
        """Register a singleton service with a factory function.

        Args:
            name: Service name.
            factory: Callable that returns the service instance.
        """
        self._singletons[name] = {"factory": factory, "instance": None}
        logger.debug("registry.singleton_registered", name=name)

    def register_factory(self, name: str, factory: callable) -> None:
        """Register a factory that creates a new instance each time.

        Args:
            name: Service name.
            factory: Callable that returns a new service instance.
        """
        self._factories[name] = factory
        logger.debug("registry.factory_registered", name=name)

    def override(self, name: str, instance: Any) -> None:
        """Override a service instance (useful for testing).

        Args:
            name: Service name.
            instance: The instance to use instead.
        """
        self._overrides[name] = instance
        logger.debug("registry.override_set", name=name)

    def get(self, name: str) -> Any:
        """Get a service instance.

        For singletons, returns the cached instance (created on first access).
        For factories, creates a new instance each time.
        For overrides, returns the override instance.

        Args:
            name: Service name.

        Returns:
            The service instance.

        Raises:
            KeyError: If service name is not registered.
        """
        # Check overrides first
        if name in self._overrides:
            return self._overrides[name]

        # Check singletons
        if name in self._singletons:
            entry = self._singletons[name]
            if entry["instance"] is None:
                entry["instance"] = entry["factory"]()
                logger.debug("registry.singleton_created", name=name)
            return entry["instance"]

        # Check factories
        if name in self._factories:
            return self._factories[name]()

        raise KeyError(f"Service '{name}' is not registered")

    def get_optional(self, name: str, default: Any = None) -> Any:
        """Get a service instance or return default if not registered."""
        try:
            return self.get(name)
        except KeyError:
            return default

    def has(self, name: str) -> bool:
        """Check if a service is registered."""
        return name in self._singletons or name in self._factories or name in self._overrides

    def reset(self) -> None:
        """Reset all services (useful for testing)."""
        self._singletons.clear()
        self._factories.clear()
        self._overrides.clear()
        logger.debug("registry.reset")

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "singletons": len(self._singletons),
            "factories": len(self._factories),
            "overrides": len(self._overrides),
            "initialized": {k: v["instance"] is not None for k, v in self._singletons.items()},
        }


# Global registry instance
_registry: Optional[ServiceRegistry] = None


def get_registry() -> ServiceRegistry:
    """Get or create global service registry."""
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
    return _registry


def setup_services() -> ServiceRegistry:
    """Set up all services in the registry."""
    registry = get_registry()

    # Register singletons
    registry.register_singleton("job_analyzer", lambda: _create_job_analyzer())
    registry.register_singleton("monitor_service", lambda: _create_monitor_service())
    registry.register_singleton("blacklist_service", lambda: _create_blacklist_service())
    registry.register_singleton("event_bus", lambda: _create_event_bus())
    registry.register_singleton("ai_cache", lambda: _create_ai_cache())
    registry.register_singleton("database", lambda: _create_database())

    return registry


def _create_job_analyzer():
    from services.job_analyzer import JobAnalyzer
    return JobAnalyzer()


def _create_monitor_service():
    from services.monitor import MonitorService
    return MonitorService()


def _create_blacklist_service():
    from services.blacklist import BlacklistService
    from config import DB_PATH
    return BlacklistService(DB_PATH)


def _create_event_bus():
    from services.event_bus import get_event_bus
    return get_event_bus()


def _create_ai_cache():
    from services.ai_cache import get_ai_cache
    return get_ai_cache()


def _create_database():
    from db.database import get_database
    return get_database()
