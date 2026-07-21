"""Auth middleware for python-telegram-bot 20.x.

Re-exports from bot.auth for backward compatibility.
"""
from bot.auth import owner_only, check_owner, deny_access

__all__ = ["owner_only", "check_owner", "deny_access"]
