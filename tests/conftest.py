"""Pytest conftest: set required environment variables for tests."""
import os

# Set required env vars for tests that import modules needing them
os.environ.setdefault("BOT_TOKEN", "test_bot_token_12345")
os.environ.setdefault("OWNER_CHAT_ID", "123456789")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-mock-key")
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "test_hash")
