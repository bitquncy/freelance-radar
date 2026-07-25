"""Text router for pending V2 input flows (proposal edit, CRM note, channel add).

A single MessageHandler that consumes plain text ONLY when a pending-input
key was set by a callback handler; otherwise it does nothing and legacy
handlers are unaffected.
"""
from telegram import Update
from telegram.ext import BaseHandler, ContextTypes, MessageHandler, filters


async def v2_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch pending text input to the flow that requested it."""
    if update.message is None or update.message.text is None:
        return
    text = update.message.text
    user_data = context.user_data or {}
    if user_data.get("v2_edit_proposal"):
        from bot.handlers.v2.proposals import apply_proposal_edit

        await apply_proposal_edit(update, context, text)
        return
    if user_data.get("v2_note_client"):
        from bot.handlers.v2.crm_handlers import apply_client_note

        await apply_client_note(update, context, text)
        return
    if user_data.pop("v2_add_channel", None):
        from bot.handlers.v2.sources import add_channel_from_text

        await add_channel_from_text(update, context, text)
        return


def get_text_router() -> BaseHandler:
    """Build the pending-input text router."""
    return MessageHandler(filters.TEXT & ~filters.COMMAND, v2_text_router)
