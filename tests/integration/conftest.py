"""Shared fixtures for integration tests.

The filter integration tests exercise budget/whitelist/rating logic — the
blacklist DB lookup is mocked here (as the unit tests already do), so the
suite does not depend on an initialized legacy SQLite schema.
"""
import pytest

from services.blacklist import BlacklistService


@pytest.fixture(autouse=True)
def mock_blacklist_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Short-circuit blacklist checks: nothing is blacklisted in these tests."""

    async def _not_blacklisted(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(BlacklistService, "check_vacancy", _not_blacklisted)
    monkeypatch.setattr(BlacklistService, "is_blacklisted", _not_blacklisted)
