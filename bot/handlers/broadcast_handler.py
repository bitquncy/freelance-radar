"""Админский UX безопасной рассылки по разрешённым Telegram-чатам."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import telegram
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.auth import owner_only
from config import BROADCAST_TIMEZONE, OWNER_CHAT_ID
from emoji_config import (
    P,
    danger_button,
    inline_button,
    neutral_button,
    primary_button,
    success_button,
)
from services.broadcast.repository import BroadcastRepository, GroupRecord
from services.logger_config import get_logger

logger = get_logger(__name__)

(
    ENTERING_GROUP_NAME,
    ADDING_CHAT,
    SELECTING_GROUP,
    SELECTING_FILTERS,
    ENTERING_MESSAGE,
    COLLECTING_ALBUM,
    CHOOSING_BUTTONS,
    ENTERING_BUTTONS,
    CONFIRMING,
    ENTERING_SCHEDULE,
) = range(10)

_DRAFT_KEYS = (
    "broadcast_group_id",
    "broadcast_filters",
    "broadcast_source_chat_id",
    "broadcast_source_message_ids",
    "broadcast_content_type",
    "broadcast_media_group_id",
    "broadcast_reply_markup",
)


def _repository() -> BroadcastRepository:
    return BroadcastRepository()


@owner_only
async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть админский раздел рассылок."""
    if update.message is None:
        return
    await update.message.reply_text(
        f"{P.MEGAPHONE} Рассылка сообщений\n\n"
        "Только чаты, где бот уже имеет право публиковать. "
        "Автопоиск и вступление в чужие группы отключены.",
        reply_markup=_main_keyboard(),
    )


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                success_button(
                    "Создать группу чатов",
                    icon=P.PLUS,
                    callback_data="bcast_group_create",
                )
            ],
            [
                primary_button(
                    "Мои группы", icon=P.LIST, callback_data="bcast_group_list"
                )
            ],
            [
                success_button(
                    "Новая рассылка",
                    icon=P.INBOX,
                    callback_data="bcast_send_start",
                )
            ],
            [
                primary_button(
                    "История рассылок",
                    icon=P.SCROLL,
                    callback_data="bcast_history",
                )
            ],
            [neutral_button("Назад", icon=P.PREV, callback_data="back_to_main")],
        ]
    )


@owner_only
async def create_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Новая группа чатов\n\nВведите название (1–100 символов):",
        reply_markup=_cancel_keyboard(),
    )
    return ENTERING_GROUP_NAME


@owner_only
async def save_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not 1 <= len(name) <= 100:
        await update.message.reply_text("Название должно содержать 1–100 символов.")
        return ENTERING_GROUP_NAME
    try:
        group_id = await _repository().create_group(OWNER_CHAT_ID, name)
    except IntegrityError:
        await update.message.reply_text("Группа с таким названием уже есть.")
        return ENTERING_GROUP_NAME
    context.user_data["current_group_id"] = group_id
    await update.message.reply_text(
        f"Группа «{name}» создана.\n\n"
        "Присылайте chat_id, @username или https://t.me/username.\n"
        "/done — завершить.",
        reply_markup=_cancel_keyboard(),
    )
    return ADDING_CHAT


@owner_only
async def add_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id = context.user_data.get("current_group_id")
    if not group_id:
        await update.message.reply_text("Группа не найдена. Начните заново.")
        return ConversationHandler.END
    resolved = await _resolve_authorized_chat(update.message.text or "", context)
    if resolved is None:
        await update.message.reply_text(
            "Не удалось подтвердить право публикации. "
            "Добавьте бота и выдайте ему права, затем повторите."
        )
        return ADDING_CHAT
    saved = await _repository().add_recipient(
        group_id=int(group_id),
        owner_telegram_id=OWNER_CHAT_ID,
        **resolved,
    )
    if not saved:
        await update.message.reply_text("Группа не найдена.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"Чат {resolved['title'] or resolved['chat_id']} добавлен. "
        "Пришлите следующий или /done."
    )
    return ADDING_CHAT


async def _resolve_authorized_chat(
    text: str, context: ContextTypes.DEFAULT_TYPE
) -> dict[str, Any] | None:
    text = text.strip()
    match = re.fullmatch(r"https?://t\.me/([^/?#]+).*", text)
    candidate = f"@{match.group(1).lstrip('@')}" if match else text
    if not re.fullmatch(r"-?\d+|@[A-Za-z0-9_]{5,}", candidate):
        return None
    try:
        chat = await context.bot.get_chat(candidate)
        membership = await context.bot.get_chat_member(chat.id, context.bot.id)
    except (telegram.error.TelegramError, ValueError, TypeError) as exc:
        logger.warning("broadcast.resolve_failed", reference=text, error=str(exc))
        return None
    status = getattr(membership.status, "value", str(membership.status))
    chat_type = getattr(chat.type, "value", str(chat.type))
    if status in {"left", "kicked"}:
        return None
    if chat_type == "channel" and status not in {"administrator", "creator", "owner"}:
        return None
    if status == "restricted" and not bool(
        getattr(membership, "can_send_messages", False)
    ):
        return None
    member_user = getattr(membership, "user", None)
    return {
        "chat_id": int(chat.id),
        "chat_type": chat_type,
        "title": chat.title or chat.full_name or chat.username or str(chat.id),
        "username": chat.username,
        "language_code": getattr(member_user, "language_code", None),
    }


@owner_only
async def done_adding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id = context.user_data.pop("current_group_id", None)
    members = await _repository().list_recipients(int(group_id)) if group_id else []
    await update.message.reply_text(
        f"Группа готова. Активных чатов: {len(members)}.",
        reply_markup=_main_keyboard(),
    )
    return ConversationHandler.END


@owner_only
async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    groups = await _repository().list_groups(OWNER_CHAT_ID)
    if not groups:
        await query.edit_message_text("Групп пока нет.", reply_markup=_main_keyboard())
        return
    rows = []
    lines = ["Мои группы:"]
    repository = _repository()
    for group in groups:
        count = len(await repository.list_recipients(group.id))
        lines.append(f"• {group.name}: {count}")
        rows.append(
            [
                inline_button(
                    f"{group.name} ({count})",
                    icon=P.EYE,
                    callback_data=f"bcast_group_detail_{group.id}",
                ),
                danger_button(
                    "Удалить",
                    icon=P.TRASH,
                    callback_data=f"bcast_group_delete_{group.id}",
                ),
            ]
        )
    rows.append([neutral_button("Назад", icon=P.PREV, callback_data="back_to_main")])
    await query.edit_message_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows)
    )


@owner_only
async def group_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    group_id = int(query.data.removeprefix("bcast_group_detail_"))
    repository = _repository()
    group = await repository.get_group(group_id, OWNER_CHAT_ID)
    if group is None:
        await query.edit_message_text("Группа не найдена.")
        return
    members = await repository.list_recipients(group_id)
    lines = [f"Группа: {group.name}", f"Чатов: {len(members)}", ""]
    lines.extend(
        f"• {member.title or member.chat_id} [{member.chat_type}]"
        for member in members[:20]
    )
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    success_button(
                        "Добавить чат",
                        icon=P.PLUS,
                        callback_data=f"bcast_group_add_chat_{group.id}",
                    )
                ],
                [
                    primary_button(
                        "К списку", icon=P.PREV, callback_data="bcast_group_list"
                    )
                ],
            ]
        ),
    )


@owner_only
async def add_chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id = int(query.data.removeprefix("bcast_group_add_chat_"))
    if await _repository().get_group(group_id, OWNER_CHAT_ID) is None:
        await query.edit_message_text("Группа не найдена.")
        return ConversationHandler.END
    context.user_data["current_group_id"] = group_id
    await query.edit_message_text(
        "Пришлите chat_id, @username или ссылку. /done — завершить.",
        reply_markup=_cancel_keyboard(),
    )
    return ADDING_CHAT


@owner_only
async def delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    group_id = int(query.data.removeprefix("bcast_group_delete_"))
    try:
        deleted = await _repository().delete_group(group_id, OWNER_CHAT_ID)
    except IntegrityError:
        await query.edit_message_text(
            "Группа уже использовалась в рассылке и сохранена для истории.",
            reply_markup=_main_keyboard(),
        )
        return
    await query.edit_message_text(
        "Группа удалена." if deleted else "Группа не найдена.",
        reply_markup=_main_keyboard(),
    )


@owner_only
async def send_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    groups = await _repository().list_groups(OWNER_CHAT_ID)
    if not groups:
        await query.edit_message_text(
            "Сначала создайте группу чатов.", reply_markup=_main_keyboard()
        )
        return ConversationHandler.END
    rows = [
        [
            inline_button(
                group.name,
                icon=P.PEOPLE,
                callback_data=f"bcast_select_group_{group.id}",
            )
        ]
        for group in groups
    ]
    rows.append([neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_cancel")])
    await query.edit_message_text(
        "Выберите ручной сегмент:", reply_markup=InlineKeyboardMarkup(rows)
    )
    return SELECTING_GROUP


@owner_only
async def group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id = int(query.data.removeprefix("bcast_select_group_"))
    group = await _repository().get_group(group_id, OWNER_CHAT_ID)
    if group is None:
        await query.edit_message_text("Группа не найдена.")
        return ConversationHandler.END
    context.user_data["broadcast_group_id"] = group_id
    context.user_data["broadcast_filters"] = {"chat_types": [], "languages": []}
    return await _render_filters(query, group, context)


@owner_only
async def change_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    group_id = context.user_data.get("broadcast_group_id")
    group = (
        await _repository().get_group(int(group_id), OWNER_CHAT_ID)
        if group_id
        else None
    )
    if group is None:
        await query.edit_message_text("Группа не найдена.")
        return ConversationHandler.END
    action = query.data.removeprefix("bcast_filter_")
    current = context.user_data.setdefault(
        "broadcast_filters", {"chat_types": [], "languages": []}
    )
    if action.startswith("type_"):
        value = action.removeprefix("type_")
        current["chat_types"] = [] if value == "all" else _chat_type_values(value)
    elif action.startswith("lang_"):
        value = action.removeprefix("lang_")
        current["languages"] = [] if value == "all" else [value]
    elif action == "done":
        count = await _repository().count_recipients(group.id, current)
        if count == 0:
            await query.answer("Под фильтр не попало ни одного чата.", show_alert=True)
            return SELECTING_FILTERS
        await query.answer()
        await query.edit_message_text(
            f"Получателей: {count}.\n\n"
            "Пришлите текст, фото, видео, документ или альбом."
        )
        return ENTERING_MESSAGE
    await query.answer()
    return await _render_filters(query, group, context)


async def _render_filters(
    query: Any, group: GroupRecord, context: ContextTypes.DEFAULT_TYPE
) -> int:
    current = context.user_data["broadcast_filters"]
    count = await _repository().count_recipients(group.id, current)
    types = current.get("chat_types") or []
    languages = current.get("languages") or []
    selected_type = (
        "private"
        if types == ["private"]
        else (
            "group"
            if set(types) == {"group", "supergroup"}
            else "channel" if types == ["channel"] else "all"
        )
    )
    selected_language = languages[0] if len(languages) == 1 else "all"

    def mark(label: str, value: str, selected: str) -> str:
        return f"✓ {label}" if value == selected else label

    rows = [
        [
            primary_button(
                mark("Все типы", "all", selected_type),
                callback_data="bcast_filter_type_all",
            ),
            primary_button(
                mark("Личные", "private", selected_type),
                callback_data="bcast_filter_type_private",
            ),
        ],
        [
            primary_button(
                mark("Группы", "group", selected_type),
                callback_data="bcast_filter_type_group",
            ),
            primary_button(
                mark("Каналы", "channel", selected_type),
                callback_data="bcast_filter_type_channel",
            ),
        ],
        [
            primary_button(
                mark("Любой язык", "all", selected_language),
                callback_data="bcast_filter_lang_all",
            ),
            primary_button(
                mark("RU", "ru", selected_language),
                callback_data="bcast_filter_lang_ru",
            ),
            primary_button(
                mark("EN", "en", selected_language),
                callback_data="bcast_filter_lang_en",
            ),
        ],
        [
            success_button(
                f"Далее · {count}", icon=P.CHECK, callback_data="bcast_filter_done"
            )
        ],
        [neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_cancel")],
    ]
    await query.edit_message_text(
        f"Сегмент: {group.name}\nВыберите тип чата и язык:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return SELECTING_FILTERS


def _chat_type_values(value: str) -> list[str]:
    if value == "group":
        return ["group", "supergroup"]
    return [value]


@owner_only
async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    if message is None:
        return ENTERING_MESSAGE
    context.user_data["broadcast_source_chat_id"] = message.chat_id
    if message.media_group_id:
        context.user_data["broadcast_media_group_id"] = message.media_group_id
        context.user_data["broadcast_source_message_ids"] = [message.message_id]
        context.user_data["broadcast_content_type"] = "media_group"
        await message.reply_text(
            "Альбом принимаю. Когда все файлы загрузятся, нажмите /done."
        )
        return COLLECTING_ALBUM
    context.user_data["broadcast_source_message_ids"] = [message.message_id]
    context.user_data["broadcast_content_type"] = "copy"
    return await _choose_buttons(message, context)


@owner_only
async def collect_album(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    if message is None or message.media_group_id != context.user_data.get(
        "broadcast_media_group_id"
    ):
        await update.effective_message.reply_text(
            "Дождитесь загрузки текущего альбома и нажмите /done."
        )
        return COLLECTING_ALBUM
    ids = context.user_data.setdefault("broadcast_source_message_ids", [])
    if message.message_id not in ids:
        ids.append(message.message_id)
    return COLLECTING_ALBUM


@owner_only
async def finish_album(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ids = context.user_data.get("broadcast_source_message_ids") or []
    if not 2 <= len(ids) <= 10:
        await update.message.reply_text(
            f"В альбоме собрано {len(ids)} элементов; нужно от 2 до 10."
        )
        return COLLECTING_ALBUM
    ids.sort()
    return await _choose_buttons(update.message, context)


async def _choose_buttons(message: Any, context: ContextTypes.DEFAULT_TYPE) -> int:
    await message.reply_text(
        "Добавить URL-кнопки?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    success_button(
                        "Добавить", icon=P.PLUS, callback_data="bcast_buttons_add"
                    )
                ],
                [primary_button("Без кнопок", callback_data="bcast_buttons_skip")],
                [neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_cancel")],
            ]
        ),
    )
    return CHOOSING_BUTTONS


@owner_only
async def choose_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "bcast_buttons_add":
        await query.edit_message_text(
            "Пришлите до 8 кнопок, каждую с новой строки:\n"
            "Текст | https://example.com"
        )
        return ENTERING_BUTTONS
    context.user_data["broadcast_reply_markup"] = None
    return await _show_preview(query.message, context)


@owner_only
async def receive_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["broadcast_reply_markup"] = _parse_buttons(
            update.message.text or ""
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return ENTERING_BUTTONS
    return await _show_preview(update.message, context)


def _parse_buttons(text: str) -> list[list[dict[str, str]]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not 1 <= len(lines) <= 8:
        raise ValueError("Укажите от 1 до 8 кнопок.")
    rows: list[list[dict[str, str]]] = []
    for line in lines:
        label, separator, url = line.partition("|")
        label = label.strip()
        url = url.strip()
        parsed = urlparse(url)
        if not separator or not 1 <= len(label) <= 64:
            raise ValueError("Формат кнопки: Текст | https://example.com")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Допустимы только полные HTTP/HTTPS-ссылки.")
        rows.append([{"text": label, "url": url}])
    return rows


async def _show_preview(message: Any, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id = int(context.user_data["broadcast_group_id"])
    current_filters = context.user_data["broadcast_filters"]
    count = await _repository().count_recipients(group_id, current_filters)
    ids = context.user_data.get("broadcast_source_message_ids") or []
    content = "медиагруппа" if len(ids) > 1 else "копия сообщения"
    buttons = context.user_data.get("broadcast_reply_markup") or []
    await message.reply_text(
        f"Предпросмотр\n\nТип: {content}\n"
        f"Элементов: {len(ids)}\nURL-кнопок: {len(buttons)}\n"
        f"Получателей: {count}\n\nПроверьте исходное сообщение выше.",
        reply_markup=_confirm_keyboard(),
    )
    return CONFIRMING


@owner_only
async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "bcast_confirm_schedule":
        await query.edit_message_text(
            f"Введите время в {BROADCAST_TIMEZONE}: ДД.ММ.ГГГГ ЧЧ:ММ"
        )
        return ENTERING_SCHEDULE
    if query.data == "bcast_confirm_now":
        return await _enqueue(update, context, None)
    await query.edit_message_text("Рассылка отменена.", reply_markup=_main_keyboard())
    _clear_draft(context)
    return ConversationHandler.END


@owner_only
async def receive_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        timezone_info = ZoneInfo(BROADCAST_TIMEZONE)
        value = datetime.strptime((update.message.text or "").strip(), "%d.%m.%Y %H:%M")
        scheduled_at = value.replace(tzinfo=timezone_info)
    except (ValueError, ZoneInfoNotFoundError):
        await update.message.reply_text("Неверный формат. Пример: 31.12.2026 18:30")
        return ENTERING_SCHEDULE
    if scheduled_at <= datetime.now(timezone_info):
        await update.message.reply_text("Время должно быть в будущем.")
        return ENTERING_SCHEDULE
    return await _enqueue(update, context, scheduled_at)


async def _enqueue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    scheduled_at: datetime | None,
) -> int:
    message = update.callback_query.message if update.callback_query else update.message
    try:
        broadcast_id, total = await _repository().create_broadcast(
            owner_telegram_id=OWNER_CHAT_ID,
            group_id=int(context.user_data["broadcast_group_id"]),
            source_chat_id=int(context.user_data["broadcast_source_chat_id"]),
            source_message_ids=list(context.user_data["broadcast_source_message_ids"]),
            content_type=str(context.user_data["broadcast_content_type"]),
            reply_markup=context.user_data.get("broadcast_reply_markup"),
            filters=dict(context.user_data["broadcast_filters"]),
            progress_chat_id=message.chat_id,
            progress_message_id=message.message_id,
            scheduled_at=scheduled_at,
        )
    except (KeyError, TypeError, ValueError, SQLAlchemyError) as exc:
        logger.exception("broadcast.enqueue_failed")
        await message.reply_text(f"Не удалось создать рассылку: {type(exc).__name__}")
        _clear_draft(context)
        return ConversationHandler.END
    text = (
        f"Рассылка #{broadcast_id} запланирована. Получателей: {total}."
        if scheduled_at
        else f"Рассылка #{broadcast_id} поставлена в очередь. Получателей: {total}."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        progress = await update.message.reply_text(text)
        await _repository().set_progress_message(broadcast_id, progress.message_id)
    runner = context.application.bot_data.get("broadcast_runner")
    if runner is not None and scheduled_at is None:
        context.application.create_task(runner.run_due())
    _clear_draft(context)
    return ConversationHandler.END


@owner_only
async def broadcast_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    campaigns = await _repository().history(OWNER_CHAT_ID)
    if not campaigns:
        await query.edit_message_text(
            "Рассылок пока нет.", reply_markup=_main_keyboard()
        )
        return
    lines = ["Последние рассылки:", ""]
    for campaign in campaigns:
        lines.append(
            f"#{campaign.id} · {campaign.status.value} · "
            f"{campaign.sent_count}/{campaign.total_count} · "
            f"{campaign.created_at:%d.%m %H:%M}"
        )
    await query.edit_message_text("\n".join(lines), reply_markup=_main_keyboard())


@owner_only
async def control_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, raw_id = query.data.removeprefix("bcast_").split("_", maxsplit=1)
    target_status = {"pause": "paused", "resume": "queued", "stop": "cancelled"}[action]
    changed = await _repository().set_status(int(raw_id), target_status)
    await query.answer(
        (
            {
                "pause": "Рассылка на паузе.",
                "resume": "Рассылка продолжена.",
                "stop": "Рассылка остановлена.",
            }[action]
            if changed
            else "Статус уже изменён."
        ),
        show_alert=not changed,
    )
    runner = context.application.bot_data.get("broadcast_runner")
    if changed and runner is not None:
        context.application.create_task(runner.run_due())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(context)
    context.user_data.pop("current_group_id", None)
    message = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()
    await message.reply_text("Действие отменено.", reply_markup=_main_keyboard())
    return ConversationHandler.END


async def conversation_timeout(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    _clear_draft(context)
    context.user_data.pop("current_group_id", None)
    if update.effective_message:
        await update.effective_message.reply_text(
            "Черновик рассылки закрыт после 15 минут бездействия."
        )
    return ConversationHandler.END


def _clear_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in _DRAFT_KEYS:
        context.user_data.pop(key, None)


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_cancel")]]
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                success_button(
                    "Отправить сейчас", icon=P.CHECK, callback_data="bcast_confirm_now"
                )
            ],
            [
                primary_button(
                    "Запланировать",
                    icon=P.TIMER,
                    callback_data="bcast_confirm_schedule",
                )
            ],
            [neutral_button("Отмена", icon=P.CROSS, callback_data="bcast_confirm_no")],
        ]
    )


def get_broadcast_handler() -> ConversationHandler:
    """Собрать Redis-persistent FSM с 15-минутным timeout."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("broadcast", broadcast_menu),
            CallbackQueryHandler(create_group_start, pattern=r"^bcast_group_create$"),
            CallbackQueryHandler(add_chat_start, pattern=r"^bcast_group_add_chat_\d+$"),
            CallbackQueryHandler(send_start, pattern=r"^bcast_send_start$"),
        ],
        states={
            ENTERING_GROUP_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_group_name)
            ],
            ADDING_CHAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_chat),
                CommandHandler("done", done_adding),
            ],
            SELECTING_GROUP: [
                CallbackQueryHandler(
                    group_selected, pattern=r"^bcast_select_group_\d+$"
                )
            ],
            SELECTING_FILTERS: [
                CallbackQueryHandler(change_filters, pattern=r"^bcast_filter_")
            ],
            ENTERING_MESSAGE: [
                MessageHandler(filters.ALL & ~filters.COMMAND, receive_message)
            ],
            COLLECTING_ALBUM: [
                MessageHandler(filters.ALL & ~filters.COMMAND, collect_album),
                CommandHandler("done", finish_album),
            ],
            CHOOSING_BUTTONS: [
                CallbackQueryHandler(
                    choose_buttons, pattern=r"^bcast_buttons_(?:add|skip)$"
                )
            ],
            ENTERING_BUTTONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_buttons)
            ],
            CONFIRMING: [
                CallbackQueryHandler(confirm_broadcast, pattern=r"^bcast_confirm_")
            ],
            ENTERING_SCHEDULE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_schedule)
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, conversation_timeout),
                CallbackQueryHandler(conversation_timeout),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^bcast_cancel$"),
            CommandHandler("cancel", cancel),
        ],
        per_user=True,
        per_chat=True,
        name="broadcast_conversation",
        persistent=True,
        conversation_timeout=15 * 60,
    )


def get_broadcast_handlers() -> list[Any]:
    return [
        get_broadcast_handler(),
        CallbackQueryHandler(list_groups, pattern=r"^bcast_group_list$"),
        CallbackQueryHandler(group_detail, pattern=r"^bcast_group_detail_\d+$"),
        CallbackQueryHandler(delete_group, pattern=r"^bcast_group_delete_\d+$"),
        CallbackQueryHandler(broadcast_history, pattern=r"^bcast_history$"),
        CallbackQueryHandler(
            control_broadcast, pattern=r"^bcast_(?:pause|resume|stop)_\d+$"
        ),
    ]
