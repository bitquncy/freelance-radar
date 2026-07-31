"""Кастомные Telegram-эмодзи + единый набор иконок и кнопок бота.

Как это работает
----------------
Premium-эмодзи существуют ТОЛЬКО как HTML-тег ``<tg-emoji emoji-id="...">``,
и Telegram парсит его исключительно в тексте сообщений, отправленных с
``parse_mode="HTML"``. Поэтому набора два:

* :class:`E` — для текста сообщений (HTML). Отдаёт ``<tg-emoji>`` когда
  ``USE_PREMIUM_EMOJI=1``, иначе обычный Unicode.
* :class:`P` — plain Unicode. Обязателен для подписей кнопок
  (``InlineKeyboardButton``), ``answer(show_alert=True)``, логов и
  Markdown-текстов: там HTML не парсится и тег протёк бы как текст.

Если ID эмодзи не найден в :data:`CUSTOM_EMOJIS`, отдаётся обычный Unicode —
бот никогда не ломается из-за неполного маппинга.

Как получить ID: добавить пак https://t.me/addemoji/tgmacicons, отправить
эмодзи боту @userinfobot и скопировать ID из ответа.
"""
import os
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


#: Plain Unicode — безопасное поведение по умолчанию. Premium включается явно.
#: Значение на момент импорта; :func:`premium_enabled` перечитывает окружение,
#: если флаг выставили позже (тесты, отложенная конфигурация).
USE_PREMIUM_EMOJI = _env_bool("USE_PREMIUM_EMOJI", False)


def premium_enabled() -> bool:
    """Включены ли premium-эмодзи сейчас.

    Переменная окружения имеет приоритет над значением на момент импорта,
    иначе иконки «застывали бы» в режиме, активном при загрузке модуля.
    """
    return _env_bool("USE_PREMIUM_EMOJI", USE_PREMIUM_EMOJI)

_PLACEHOLDER = "ЗАМЕНИТЕ_НА_REAL_ID"

#: Маппинг Unicode эмодзи -> ID кастомного (premium) эмодзи.
#: Основной визуальный набор: https://t.me/addemoji/techbybirdanimatedemoji.
CUSTOM_EMOJIS: Dict[str, str] = {
    # Интерфейс / навигация
    "🏘": "5257963315258204021",
    "🏠": "5257963315258204021",
    "👤": "5278570220452091808",
    "👥": "5343952421699754096",
    "👩": "5260399854500191689",
    "👨‍💼": "5260399854500191689",
    "🗓": "5258105663359294787",
    "📅": "6039797442172424479",
    # Статусы
    "✅": "5278732510086336319",
    "✓": "5260726538302660868",
    "❌": "5260342697075416641",
    "✗": "5260342697075416641",
    "❗": "5258474669769497337",
    "⚠️": "5280649719062763659",
    "🚫": "5260249440450520061",
    "🤚": "5260249440450520061",
    "⛔": "5260342697075416641",
    "🔒": "5314668484272081062",
    # Информация и действия
    "📌": "5258461531464539536",
    "🏷": "5258461531464539536",
    "🔗": "5346180663617818112",
    "📍": "5258509201306557640",
    "➕": "5258108352008823107",
    "🔄": "5282820528678146342",
    "🔁": "5258420634785947640",
    "📸": "5258205968025525531",
    "⭐": "5352643623030657164",
    "⭐️": "5352643623030657164",
    "🌟": "5258165702707125574",
    "🔎": "5278359505061581661",
    "🔍": "5278359505061581661",
    "👁": "5400145841065313635",
    "👀": "5400145841065313635",
    "📂": "5257969839313526622",
    "🎨": "5258450450448915742",
    "👨‍🎨": "5258450450448915742",
    "👩‍🎨": "5258215635996908355",
    "💈": "5258215635996908355",
    "🔢": "5226513232549664618",
    "🆔": "5226513232549664618",
    # Время
    "🕘": "5199457120428249992",
    "⏲": "5258258882022612173",
    "⏱": "5258258882022612173",
    "🕐": "5411478155225476747",
    "⏰": "5258258882022612173",
    "⏳": "5280628742442490765",
    # Деньги, тексты, работа
    "💰": "5278565208225257317",
    "💳": "5285230937339106944",
    "📝": "5409302586786329687",
    "📋": "5257965174979042426",
    "📄": "5257965174979042426",
    "📜": "5257965174979042426",
    "💡": "5357164561440981320",
    "📖": "6039338572161486731",
    "📭": "5258328383183396223",
    "💬": "5463400358464231113",
    "📊": "5283181258686372998",
    "📈": "5258330865674494479",
    "🍑": "5258330865674494479",
    # Отправка / редактирование / энергия
    "✈️": "5201773477895356190",
    "📤": "5411355233261465958",
    "📨": "5411355233261465958",
    "✍️": "5258331647358540449",
    "✏️": "5258331647358540449",
    "👏": "5258501105293205250",
    "🎉": "5258501105293205250",
    "⚡": "5258152182150077732",
    "🎯": "5258152182150077732",
    "🚀": "5348584939065482800",
    "🔥": "5258152182150077732",
    # Семантические алиасы: в паке tgmacicons нет отдельной иконки,
    # но есть близкая по смыслу — лучше переиспользовать, чем терять стиль.
    "💼": "5257969839313526622",  # портфолио ≈ папка
    "❓": "5231463659099695141",
    "🗑": "5460929111591525382",
    "⚙️": "5409119165912986993",
    # Легаси-уведомления и форматтеры
    "📦": "5257969839313526622",  # посылка ≈ папка
    "📁": "5257969839313526622",
    "🔔": "5348377685418630139",
    "🚨": "5258474669769497337",  # авария ≈ предупреждение
    "🚩": "5258474669769497337",
    "💾": "5409196337885361177",
    "💽": "5409196337885361177",
    "⬅️": "5323454338092280794",
    "➡️": "5323481160163041855",
    "📢": "5285493480099977431",
    # «👁» (просмотрено) уже сопоставлен выше, в блоке действий.
    # Прочее
    "ℹ️": "5258503720928288433",
    "⬇️": "5258336354642697821",
    "👇": "5258336354642697821",
    "📞": "5411604122321302582",
    "☎️": "5411604122321302582",
    "📱": "5411604122321302582",
    "🤙": "5418325110484387058",
    "🤖": "5217686069734034873",
}


def emoji(unicode_emoji: str, fallback: bool = True) -> str:
    """Вернуть premium-эмодзи в виде HTML-тега либо обычный Unicode.

    Использовать ТОЛЬКО в тексте, отправляемом с ``parse_mode="HTML"``.
    Для кнопок и alert-ов брать :class:`P`.
    """
    if not premium_enabled():
        return unicode_emoji if fallback else ""
    emoji_id = CUSTOM_EMOJIS.get(unicode_emoji)
    if emoji_id and emoji_id != _PLACEHOLDER:
        return f'<tg-emoji emoji-id="{emoji_id}">{unicode_emoji}</tg-emoji>'
    return unicode_emoji if fallback else ""


class P:
    """Plain Unicode-иконки — единственный корректный вариант для кнопок,
    ``show_alert``-попапов, Markdown-текстов и логов (там HTML не парсится).
    """

    # Навигация / разделы
    HOME = "🏠"
    HOUSES = "🏘"
    BACK = "⬅️"
    FORWARD = "▶️"
    PREV = "◀️"
    RADAR = "📡"
    BRIEFCASE = "💼"
    PEOPLE = "👥"
    USER = "👤"
    SETTINGS = "⚙️"
    HELP = "❓"
    MENU_BARS = "☰"
    # Статусы
    CHECK = "✅"
    CROSS = "❌"
    WARNING = "⚠️"
    EXCLAMATION = "❗"
    LOCK = "🔒"
    BAN = "🚫"
    DENIED = "⛔"
    PAUSE = "⏸"
    GREEN = "🟢"
    YELLOW = "🟡"
    RED = "🔴"
    # Действия
    PLUS = "➕"
    RELOAD = "🔄"
    REPEAT = "🔁"
    TRASH = "🗑"
    EDIT = "✏️"
    WRITING = "✍️"
    SEND = "✈️"
    OUTBOX = "📤"
    INBOX = "📨"
    SEARCH = "🔍"
    EYE = "👁"
    EYES = "👀"
    ROCKET = "🚀"
    TARGET = "🎯"
    LIGHTNING = "⚡"
    FIRE = "🔥"
    SKIP = "⏭"
    HIDE = "🙈"
    PUZZLE = "🧩"
    ROBOT = "🤖"
    LAPTOP = "💻"
    FLASK = "🧪"
    MEGAPHONE = "📢"
    CAMERA = "📸"
    # Информация
    LIST = "📋"
    NOTE = "📝"
    DOC = "📄"
    SCROLL = "📜"
    CHART = "📊"
    GRAPH = "📈"
    BOOK = "📖"
    EMPTY = "📭"
    FOLDER = "📂"
    COMMENT = "💬"
    IDEA = "💡"
    INFO = "ℹ️"
    LINK = "🔗"
    LABEL = "🏷"
    PIN = "📌"
    LOCATION = "📍"
    ID = "🆔"
    NUMBER = "🔢"
    POINT_DOWN = "👇"
    POINT_RIGHT = "👉"
    ARROW_DOWN = "⬇️"
    ARROW_RIGHT = "➡️"
    # Деньги / подписка
    MONEY = "💰"
    CARD = "💳"
    STAR = "⭐"
    SPARKLE = "🌟"
    GIFT = "🎁"
    PARTY = "🎉"
    CLAP = "👏"
    # Время
    CLOCK = "🕐"
    TIMER = "⏱"
    HOURGLASS = "⏳"
    ALARM = "⏰"
    CALENDAR = "📅"
    CALENDAR_ALT = "🗓"
    PHONE = "📞"
    MOBILE = "📱"
    PALETTE = "🎨"
    # Легаси-мониторинг и форматтеры
    PACKAGE = "📦"
    NEW = "🆕"
    TOOLS = "🛠"
    BELL = "🔔"
    SIREN = "🚨"
    DISK = "💾"
    FILES = "📁"
    FLAG = "🚩"
    SEEN = "👁"


class _HtmlEmojiMeta(type):
    """Отдаёт HTML-версию иконки по имени константы :class:`P`.

    Значение вычисляется НА КАЖДОМ обращении, а не при импорте: иначе
    ``USE_PREMIUM_EMOJI``, выставленный после загрузки модуля (тесты,
    отложенная конфигурация), не влиял бы на уже связанные строки.
    """

    def __getattr__(cls, name: str) -> str:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            icon = getattr(P, name)
        except AttributeError as exc:  # pragma: no cover - опечатка в имени
            raise AttributeError(
                f"{name}: нет такой иконки в emoji_config.P"
            ) from exc
        return emoji(icon)

    def __dir__(cls) -> list:  # pragma: no cover - интроспекция/автодополнение
        return sorted(n for n in vars(P) if not n.startswith("_"))


class E(metaclass=_HtmlEmojiMeta):
    """HTML-иконки для текста сообщений с ``parse_mode="HTML"``.

    Имена совпадают с :class:`P`: ``E.CHECK`` — та же галочка, но как
    ``<tg-emoji>``, когда premium включён. При ``USE_PREMIUM_EMOJI=0``
    (по умолчанию) значения полностью равны :class:`P`.

    НЕ использовать в подписях кнопок, ``show_alert`` и ``BotCommand`` —
    там HTML не парсится, нужен :class:`P`.
    """


# --------------------------------------------------------------------------
# Цветные кнопки Telegram Bot API 9.4+
# --------------------------------------------------------------------------
# Bot API 9.4 поддерживает настоящий фон ``style`` (primary/success/danger)
# и отдельную premium-иконку ``icon_custom_emoji_id``. Установленная версия
# python-telegram-bot пока не объявляет эти поля в сигнатуре, но штатно
# передаёт их через ``api_kwargs``. Старые клиенты Telegram безопасно
# игнорируют незнакомое оформление и сохраняют текст/callback кнопки.

#: Основное действие (оплатить, сохранить, отправить).
BTN_PRIMARY = P.GREEN
#: Опасное/необратимое действие (удалить, чёрный список).
BTN_DANGER = P.RED
#: Требует внимания / приостановлено.
BTN_WARN = P.YELLOW
#: Нейтральная навигация (назад, в меню, обновить).
BTN_NEUTRAL = "🔵"
#: Отключённый/неактивный пункт.
BTN_MUTED = "⚪"


def btn(label: str, color: str = "", icon: str = "") -> str:
    """Собрать подпись кнопки: цветной маркер + иконка + текст.

    Всегда plain Unicode — безопасно для ``InlineKeyboardButton``.

    >>> btn("Оплатить", BTN_PRIMARY, P.CARD)
    '🟢 💳 Оплатить'
    """
    parts = [p for p in (color, icon, label) if p]
    return " ".join(parts)


def btn_primary(label: str, icon: str = "") -> str:
    """Зелёная кнопка основного действия."""
    return btn(label, BTN_PRIMARY, icon)


def btn_danger(label: str, icon: str = "") -> str:
    """Красная кнопка необратимого действия."""
    return btn(label, BTN_DANGER, icon)


def btn_warn(label: str, icon: str = "") -> str:
    """Жёлтая кнопка: требует внимания."""
    return btn(label, BTN_WARN, icon)


def btn_neutral(label: str, icon: str = "") -> str:
    """Синяя кнопка нейтральной навигации."""
    return btn(label, BTN_NEUTRAL, icon)


def inline_button(
    text: str,
    *,
    callback_data: Optional[str] = None,
    url: Optional[str] = None,
    style: Optional[str] = None,
    icon: str = "",
    **kwargs: Any,
) -> InlineKeyboardButton:
    """Создать нативно окрашенную inline-кнопку с custom emoji.

    ``icon`` — обычный Unicode из :class:`P`; соответствующий ID берётся из
    :data:`CUSTOM_EMOJIS`. Иконка не дублируется в тексте кнопки.
    """
    api_kwargs = dict(kwargs.pop("api_kwargs", {}) or {})
    if style:
        api_kwargs["style"] = style
    icon_id = CUSTOM_EMOJIS.get(icon)
    if icon_id and icon_id != _PLACEHOLDER:
        api_kwargs["icon_custom_emoji_id"] = icon_id
    return InlineKeyboardButton(
        text,
        callback_data=callback_data,
        url=url,
        api_kwargs=api_kwargs or None,
        **kwargs,
    )


def primary_button(text: str, *, icon: str = "", **kwargs: Any) -> InlineKeyboardButton:
    """Синяя primary-кнопка."""
    return inline_button(text, style="primary", icon=icon, **kwargs)


def success_button(text: str, *, icon: str = "", **kwargs: Any) -> InlineKeyboardButton:
    """Зелёная кнопка подтверждения/основного действия."""
    return inline_button(text, style="success", icon=icon, **kwargs)


def danger_button(text: str, *, icon: str = "", **kwargs: Any) -> InlineKeyboardButton:
    """Красная destructive-кнопка."""
    return inline_button(text, style="danger", icon=icon, **kwargs)


def strip_html_emoji(text: str) -> str:
    """Убрать теги ``<tg-emoji>``, оставив Unicode внутри.

    Нужно, когда HTML-текст переиспользуется там, где HTML не парсится
    (``show_alert``, логи, Markdown), чтобы тег не протёк как текст.
    """
    import re

    return re.sub(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', r"\1", text)


def check_emoji_config() -> dict:
    """Статистика маппинга и покрытия иконок интерфейса.

    ``unmapped_ui_icons`` — иконки :class:`P`, для которых в паке нет ID:
    они показываются обычным Unicode (бот при этом не ломается).
    Добавьте ID в :data:`CUSTOM_EMOJIS`, чтобы закрыть пробелы.
    """
    total = len(CUSTOM_EMOJIS)
    missing = sum(1 for v in CUSTOM_EMOJIS.values() if v == _PLACEHOLDER)
    configured = total - missing
    ui_icons = {
        name: value
        for name, value in vars(P).items()
        if isinstance(value, str) and not name.startswith("_")
    }
    unmapped = sorted(
        name for name, value in ui_icons.items() if value not in CUSTOM_EMOJIS
    )
    return {
        "total": total,
        "configured": configured,
        "missing": missing,
        "percent": round(configured / total * 100, 1) if total else 0,
        "premium_enabled": premium_enabled(),
        "ui_icons": len(ui_icons),
        "unmapped_ui_icons": unmapped,
    }
