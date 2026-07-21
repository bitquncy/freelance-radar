"""Unit tests for auth middleware."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.auth import owner_only


class TestOwnerOnly:
    @pytest.mark.asyncio
    @patch("bot.auth.OWNER_CHAT_ID", 123456)
    async def test_owner_allowed(self):
        """Test that owner can access handler."""
        mock_update = MagicMock()
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 123456
        mock_update.message = MagicMock()
        mock_context = MagicMock()

        @owner_only
        async def test_handler(update, context):
            return "success"

        result = await test_handler(mock_update, mock_context)
        assert result == "success"

    @pytest.mark.asyncio
    @patch("bot.auth.OWNER_CHAT_ID", 123456)
    async def test_non_owner_rejected_message(self):
        """Test that non-owner is rejected with message."""
        mock_update = MagicMock()
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 999999
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.callback_query = None
        mock_context = MagicMock()

        @owner_only
        async def test_handler(update, context):
            return "should not reach"

        result = await test_handler(mock_update, mock_context)
        assert result is None
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.auth.OWNER_CHAT_ID", 123456)
    async def test_non_owner_rejected_callback(self):
        """Test that non-owner is rejected with callback alert."""
        mock_update = MagicMock()
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 999999
        mock_update.message = None
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.answer = AsyncMock()
        mock_context = MagicMock()

        @owner_only
        async def test_handler(update, context):
            return "should not reach"

        result = await test_handler(mock_update, mock_context)
        assert result is None
        mock_update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.auth.OWNER_CHAT_ID", 123456)
    async def test_no_user_rejected(self):
        """Test that missing user is rejected."""
        mock_update = MagicMock()
        mock_update.effective_user = None
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()
        mock_context = MagicMock()

        @owner_only
        async def test_handler(update, context):
            return "should not reach"

        result = await test_handler(mock_update, mock_context)
        assert result is None
