"""/sort — per-user order of arriving order cards (task_0004).

Sets ``User.sort_preference``, which the worker uses to decide the delivery
order of a user's notifications; any V2 list surface can reuse the same
``core.sorting`` engine. Default (no preference) keeps the as-arrived order.
"""

from typing import List

from telegram import Update
from telegram.ext import BaseHandler, CommandHandler, ContextTypes

from bot.handlers.v2.common import get_or_create_user
from core.db import get_session_factory
from core.models import SortPreference
from emoji_config import E

#: (command key, preference, human label). Key order = the menu shown by /sort.
CHOICES = [
    ("default", SortPreference.DEFAULT, "как приходят"),
    ("score", SortPreference.SCORE, f"{E.TARGET} по вероятности получить заказ"),
    ("profitability", SortPreference.PROFITABILITY, f"{E.MONEY} по выгодности"),
    ("freshness", SortPreference.FRESHNESS, f"{E.RADAR} свежие первыми"),
]

_HELP_LINES = [
    f"{E.SETTINGS} <b>Сортировка заказов</b>",
    "",
    "В каком порядке показывать новые заказы.",
    "",
    "Выберите:",
    *(f"• <code>/sort {key}</code> — {label}" for key, _, label in CHOICES),
    "",
    "<i>По умолчанию — как приходят.</i>",
]


def _help_text(current_label: str) -> str:
    """Full /sort help including the user's current choice."""
    return (
        "\n".join(_HELP_LINES)
        + f"\n\nТекущая: <b>{current_label}</b>\n\n"
        + "Например: <code>/sort score</code>"
    )


async def set_sort_preference(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /sort: show help when no arg, else store the preference."""
    if update.message is None or update.effective_user is None:
        return
    arg = context.args[0].lower().strip() if context.args else ""  # type: ignore[attr-defined]
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        choice = next((c for c in CHOICES if c[0] == arg), None)
        if choice is None:
            current = (user.sort_preference or SortPreference.DEFAULT).value
            current_label = next(
                (label for key, pref, label in CHOICES if pref.value == current),
                current,
            )
            await update.message.reply_text(
                _help_text(current_label), parse_mode="HTML"
            )
            return
        _, preference, label = choice
        user.sort_preference = preference
        await session.commit()
    await update.message.reply_text(
        f"{E.CHECK} Сортировка заказов: <b>{label}</b>", parse_mode="HTML"
    )


def get_sort_preference_handlers() -> List[BaseHandler]:
    """Build the /sort command handler."""
    return [CommandHandler("sort", set_sort_preference)]
