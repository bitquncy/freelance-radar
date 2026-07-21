"""Unit tests for auth middleware."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from bot.auth import check_owner, deny_access, owner_only


class TestCheckOwner:
    def test_owner_allowed(self):
        """Test that owner is authorized."""
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456

        with pytest.MonkeyPatch.context() as m:
            m.setattr("bot.auth.OWNER_CHAT_ID", 123456)
            assert check_owner(update) is True

    def test_non_owner_rejected(self):
        """Test that non-owner is rejected."""
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999999

        with pytest.MonkeyPatch.context() as m:
            m.setattr("bot.auth.OWNER_CHAT_ID", 123456)
            assert check_owner(update) is False

    def test_no_user(self):
        """Test that missing user is rejected."""
        update = MagicMock()
        update.effective_user = None

        with pytest.MonkeyPatch.context() as m:
            m.setattr("bot.auth.OWNER_CHAT_ID", 123456)
            assert check_owner(update) is False


class TestDenyAccess:
    @pytest.mark.asyncio
    async def test_deny_message(self):
        """Test that access denied message is sent."""
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999999
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        update.callback_query = None

        await deny_access(update)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_deny_callback(self):
        """Test that access denied is sent for callback query."""
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999999
        update.message = None
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()

        await deny_access(update)
        update.callback_query.answer.assert_called_once()


class TestOwnerOnly:
    @pytest.mark.asyncio
    async def test_owner_allowed(self):
        """Test that owner can access handler."""
        mock_update = MagicMock()
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 123456
        mock_update.message = MagicMock()
        mock_context = MagicMock()

        with pytest.MonkeyPatch.context() as m:
            m.setattr("bot.auth.OWNER_CHAT_ID", 123456)

            @owner_only
            async def test_handler(update, context):
                return "success"

            result = await test_handler(mock_update, mock_context)
            assert result == "success"

    @pytest.mark.asyncio
    async def test_non_owner_rejected(self):
        """Test that non-owner is rejected."""
        mock_update = MagicMock()
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 999999
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()
        mock_context = MagicMock()

        with pytest.MonkeyPatch.context() as m:
            m.setattr("bot.auth.OWNER_CHAT_ID", 123456)

            @owner_only
            async def test_handler(update, context):
                return "success"

            result = await test_handler(mock_update, mock_context)
            assert result is None
