"""Unit tests for TelegramSourceParser send_message_to_chat."""
import pytest
from unittest.mock import AsyncMock

from parsers.telegram_source import TelegramSourceParser


@pytest.fixture
def parser():
    """Create TelegramSourceParser with mocked client."""
    p = TelegramSourceParser()
    p.client = AsyncMock()
    return p


class TestSendMessageToChat:
    """Test cases for send_message_to_chat."""

    @pytest.mark.asyncio
    async def test_send_message_success(self, parser):
        """Test that send_message returns False (not supported in HTTP parser)."""
        result = await parser.send_message_to_chat("test_chat", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_value_error(self, parser):
        """Test message sending with invalid chat ID."""
        parser.client.send_message = AsyncMock(side_effect=ValueError("Invalid chat ID"))
        result = await parser.send_message_to_chat("invalid_chat", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self, parser):
        """Test message sending with connection error."""
        parser.client.send_message = AsyncMock(side_effect=ConnectionError("Connection failed"))
        result = await parser.send_message_to_chat("test_chat", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_type_error(self, parser):
        """Test message sending with type error."""
        parser.client.send_message = AsyncMock(side_effect=TypeError("Type error"))
        result = await parser.send_message_to_chat("test_chat", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_os_error(self, parser):
        """Test message sending with OS error."""
        parser.client.send_message = AsyncMock(side_effect=OSError("OS error"))
        result = await parser.send_message_to_chat("test_chat", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_generic_exception(self, parser):
        """Test message sending with generic exception."""
        parser.client.send_message = AsyncMock(side_effect=Exception("Unknown error"))
        result = await parser.send_message_to_chat("test_chat", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_auto_connect(self):
        """Test that send_message returns False (not supported in HTTP parser)."""
        parser = TelegramSourceParser()
        result = await parser.send_message_to_chat("test_chat", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_empty_chat_id(self, parser):
        """Test message sending with empty chat ID."""
        parser.client.send_message = AsyncMock(side_effect=ValueError("Chat ID required"))
        result = await parser.send_message_to_chat("", "Hello!")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_empty_message(self, parser):
        """Test that send_message returns False (not supported in HTTP parser)."""
        result = await parser.send_message_to_chat("test_chat", "")
        assert result is False
