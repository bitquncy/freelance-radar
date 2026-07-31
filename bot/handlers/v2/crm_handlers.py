"""CRM bot commands: client list, cards, funnel moves, notes, reminders (§3.7–3.8)."""
from typing import List

from sqlalchemy import desc, select
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import (
    BaseHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from bot.handlers.v2.cards import STAGE_EMOJI, client_card, client_keyboard
from bot.handlers.v2.common import get_or_create_user, pending
from core import crm
from core.db import get_session_factory
from core.models import Client, Interaction, PipelineStage, Reminder
from emoji_config import E, P, inline_button, primary_button


def _list_keyboard(clients: List[Client]) -> InlineKeyboardMarkup:
    rows = [
        [
            inline_button(
                c.name[:40],
                icon=STAGE_EMOJI[c.pipeline_stage],
                callback_data=f"v2c:view:{c.id}",
            )
        ]
        for c in clients[:20]
    ]
    # Always offer a way back — an empty CRM must not be a dead-end screen.
    rows.append([primary_button("В меню", icon=P.BACK, callback_data="v2:menu")])
    return InlineKeyboardMarkup(rows)


async def clients_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clients or «👥 Клиенты» — the funnel list."""
    if update.effective_user is None:
        return
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        result = await session.execute(
            select(Client)
            .where(Client.user_id == user.id)
            .order_by(desc(Client.last_contact_at))
        )
        clients = list(result.scalars().all())
        await session.commit()
    active = [c for c in clients if c.pipeline_stage in crm.ACTIVE_STAGES]
    text = (
        f"{E.PEOPLE} <b>Клиенты</b> — активных: {len(active)} из {len(clients)}"
        if clients
        else (
            f"{E.PEOPLE} <b>Клиенты</b>\n"
            "Пока пусто. Карточка создаётся автоматически "
            "при отправке отклика."
        )
    )
    markup = _list_keyboard(clients)
    if update.message is not None:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)
    elif update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=markup
        )


async def client_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show one client card with funnel actions."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    client_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        client = await session.get(Client, client_id)
        if client is None or client.user_id != user.id:
            await query.answer(f"{P.CROSS} Клиент не найден.", show_alert=True)
            return
        result = await session.execute(
            select(Interaction)
            .where(Interaction.client_id == client.id)
            .order_by(desc(Interaction.created_at))
            .limit(3)
        )
        events = [i.content for i in result.scalars().all()]
        await session.commit()
    await query.answer()
    await query.edit_message_text(
        client_card(client, events),
        parse_mode="HTML",
        reply_markup=client_keyboard(client),
    )


async def client_stage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Move a client along the funnel (§3.7 transitions only)."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    _, _, client_id_raw, stage_raw = query.data.split(":")
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        client = await session.get(Client, int(client_id_raw))
        if client is None or client.user_id != user.id:
            await query.answer(f"{P.CROSS} Клиент не найден.", show_alert=True)
            return
        try:
            await crm.change_stage(session, client, PipelineStage(stage_raw))
        except crm.TransitionError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await session.commit()
    await client_view(update, context)


async def client_note_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Ask for a note text (finished by the text router).

    Ownership is verified here as well as on apply — callback data carries a
    raw client id that a user could forge.
    """
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    client_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        client = await session.get(Client, client_id)
        if client is None or client.user_id != user.id:
            await query.answer(f"{P.CROSS} Клиент не найден.", show_alert=True)
            return
        await session.commit()
    pending(context)["v2_note_client"] = client_id
    await query.answer()
    await query.message.reply_text(  # type: ignore[union-attr]
        "Пришлите текст заметки одним сообщением."
    )


async def apply_client_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """Store the note sent by the user (router flow)."""
    if update.effective_user is None or update.message is None:
        return
    client_id = int(pending(context).pop("v2_note_client", 0))
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        client = await session.get(Client, client_id)
        if client is None or client.user_id != user.id:
            await update.message.reply_text(f"{P.CROSS} Клиент не найден.")
            return
        note = text.strip()[:1000]
        client.notes = f"{client.notes}\n{note}".strip() if client.notes else note
        await crm.log_interaction(
            session, client, crm.InteractionType.NOTE, note, touch_contact=False
        )
        await session.commit()
    await update.message.reply_text("Заметка сохранена \U0001f4dd")


async def reminder_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «⏳ Отложить» on a reminder (§3.8)."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    reminder_id = int(query.data.split(":")[2])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        reminder = await session.get(Reminder, reminder_id)
        if reminder is None:
            await query.answer(f"{P.CROSS} Напоминание не найдено.", show_alert=True)
            return
        client = await session.get(Client, reminder.client_id)
        if client is None or client.user_id != user.id:
            await query.answer(f"{P.CROSS} Напоминание не найдено.", show_alert=True)
            return
        await crm.snooze_reminder(session, reminder)
        await session.commit()
    await query.answer(f"{P.HOURGLASS} Отложено на 24 часа.")
    delete = getattr(query.message, "delete", None)
    if delete is not None:
        await delete()


async def reminder_write(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «✍️ Написать сейчас»: complete + open the client card.

    The system never messages the client itself (§3.8) — it opens the card
    so the user writes personally.
    """
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    parts = query.data.split(":")
    reminder_id, client_id = int(parts[2]), int(parts[3])
    factory = get_session_factory()
    async with factory() as session:
        user, _ = await get_or_create_user(session, update.effective_user)
        reminder = await session.get(Reminder, reminder_id)
        client = await session.get(Client, client_id)
        if (
            reminder is None
            or client is None
            or reminder.client_id != client.id
            or client.user_id != user.id
        ):
            await query.answer(f"{P.CROSS} Напоминание не найдено.", show_alert=True)
            return
        await crm.complete_reminder(session, reminder)
        await crm.log_interaction(
            session,
            client,
            crm.InteractionType.REMINDER,
            "Пользователь пишет клиенту по напоминанию",
            touch_contact=True,
        )
        result = await session.execute(
            select(Interaction)
            .where(Interaction.client_id == client.id)
            .order_by(desc(Interaction.created_at))
            .limit(3)
        )
        events = [i.content for i in result.scalars().all()]
        await session.commit()
    await query.answer()
    await query.edit_message_text(
        client_card(client, events)
        + "\n\n✍️ <i>Самое время написать клиенту — контакты в заметках карточки.</i>",
        parse_mode="HTML",
        reply_markup=client_keyboard(client),
    )


def get_crm_handlers() -> List[BaseHandler]:
    """Build CRM handlers."""
    return [
        CommandHandler("clients", clients_list),
        CallbackQueryHandler(clients_list, pattern=r"^v2c:list$"),
        CallbackQueryHandler(client_view, pattern=r"^v2c:view:\d+$"),
        CallbackQueryHandler(client_stage, pattern=r"^v2c:stage:\d+:[a-z_]+$"),
        CallbackQueryHandler(client_note_start, pattern=r"^v2c:note:\d+$"),
        CallbackQueryHandler(reminder_snooze, pattern=r"^v2r:snooze:\d+$"),
        CallbackQueryHandler(reminder_write, pattern=r"^v2r:write:\d+:\d+$"),
    ]
