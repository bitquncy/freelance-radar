"""Кастомные Telegram-эмодзи (пак tgmacicons) + единый набор иконок бота.

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
from typing import Dict


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
CUSTOM_EMOJIS: Dict[str, str] = {
    # Интерфейс / навигация
    "🏘": "5257963315258204021",
    "🏠": "5257963315258204021",
    "👤": "5260399854500191689",
    "👥": "5258513401784573443",
    "👩": "5260399854500191689",
    "👨‍💼": "5260399854500191689",
    "🗓": "5258105663359294787",
    "📅": "5258105663359294787",
    # Статусы
    "✅": "5260726538302660868",
    "✓": "5260726538302660868",
    "❌": "5260342697075416641",
    "✗": "5260342697075416641",
    "❗": "5258474669769497337",
    "⚠️": "5258474669769497337",
    "🚫": "5260249440450520061",
    "🤚": "5260249440450520061",
    "⛔": "5260342697075416641",
    "🔒": "5258476306152038031",
    # Информация и действия
    "📌": "5258461531464539536",
    "🏷": "5258461531464539536",
    "🔗": "5258461531464539536",
    "📍": "5258509201306557640",
    "➕": "5258108352008823107",
    "🔄": "5258420634785947640",
    "🔁": "5258420634785947640",
    "📸": "5258205968025525531",
    "⭐": "5258165702707125574",
    "🌟": "5258165702707125574",
    "🔎": "5429571366384842791",
    "🔍": "5429571366384842791",
    "👁": "5253959125838090076",
    "👀": "5253959125838090076",
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
    "🕐": "5258258882022612173",
    "⏰": "5258258882022612173",
    "⏳": "5258258882022612173",
    # Деньги, тексты, работа
    "💰": "5258204546391351475",
    "💳": "5258204546391351475",
    "📝": "5257965174979042426",
    "📋": "5257965174979042426",
    "📄": "5257965174979042426",
    "📜": "5257965174979042426",
    "💡": "5258216851472654189",
    "📖": "5258328383183396223",
    "📭": "5258328383183396223",
    "💬": "5260535596941582167",
    "📊": "5258330865674494479",
    "📈": "5258330865674494479",
    "🍑": "5258330865674494479",
    # Отправка / редактирование / энергия
    "✈️": "5258073068852485953",
    "📤": "5258073068852485953",
    "📨": "5258073068852485953",
    "✍️": "5258331647358540449",
    "✏️": "5258331647358540449",
    "👏": "5258501105293205250",
    "🎉": "5258501105293205250",
    "⚡": "5258152182150077732",
    "🎯": "5258152182150077732",
    "🚀": "5258152182150077732",
    "🔥": "5258152182150077732",
    # Семантические алиасы: в паке tgmacicons нет отдельной иконки,
    # но есть близкая по смыслу — лучше переиспользовать, чем терять стиль.
    "💼": "5257969839313526622",  # портфолио ≈ папка
    "❓": "5258503720928288433",  # помощь ≈ инфо
    "🗑": "5260342697075416641",  # удалить ≈ крестик
    "⚙️": "5226513232549664618",  # настройки ≈ цифры/параметры
    # Легаси-уведомления и форматтеры
    "📦": "5257969839313526622",  # посылка ≈ папка
    "📁": "5257969839313526622",
    "🔔": "5258258882022612173",  # колокольчик ≈ таймер/напоминание
    "🚨": "5258474669769497337",  # авария ≈ предупреждение
    "🚩": "5258474669769497337",
    "💾": "5257969839313526622",
    # «👁» (просмотрено) уже сопоставлен выше, в блоке действий.
    # Прочее
    "ℹ️": "5258503720928288433",
    "⬇️": "5258336354642697821",
    "👇": "5258336354642697821",
    "📞": "5258337316715373336",
    "☎️": "5258337316715373336",
    "📱": "5258337316715373336",
    "🤙": "5258337316715373336",
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
# «Цветные» кнопки
# --------------------------------------------------------------------------
# Telegram НЕ поддерживает ни HTML, ни свой цвет фона в подписях
# InlineKeyboardButton: text рендерится как плоский plain-текст в теме
# клиента. Единственный работающий способ раскрасить кнопки — цветной
# маркер-эмодзи в начале подписи. Ниже — семантическая палитра, чтобы цвет
# означал одно и то же на всех экранах (а не «кто как раскрасил»).
#
# Внимание: НИКОГДА не оборачивать подписи кнопок в emoji()/E.* — тег
# <tg-emoji> в кнопке протечёт пользователю как сырой текст.

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
