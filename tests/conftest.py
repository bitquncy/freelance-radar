"""Pytest conftest: set required environment variables for tests.

Uses direct assignment instead of setdefault so that tests always get the
values they expect, even if the caller's environment already has these vars
(e.g. when running tests locally next to a real bot process).
"""
import os

# Force-set test env vars (overrides any existing user env values)
os.environ["BOT_TOKEN"] = "test_bot_token_12345"
os.environ["OWNER_CHAT_ID"] = "123456789"
os.environ["OPENAI_API_KEY"] = "sk-test-mock-key"
os.environ["TELEGRAM_API_ID"] = "12345"
os.environ["TELEGRAM_API_HASH"] = "test_hash"
