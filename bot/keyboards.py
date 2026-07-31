"""Keyboard layouts for the Telegram bot."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from emoji_config import P

# Единый источник истины для подписей reply-меню: они же служат
# матчерами входящего текста в ``main.py``. Держать их в одном месте
# обязательно: рассогласование сделало бы кнопки нажатыми-без-реакции.
MENU_JOBS = f"{P.LIST} Вакансии"
MENU_SETTINGS = f"{P.SETTINGS} Настройки"
MENU_SOURCES = f"{P.RADAR} Источники"
MENU_STATS = f"{P.CHART} Статистика"
MENU_PROFILE = f"{P.USER} Профиль"
MENU_HELP = f"{P.HELP} Помощь"

#: Порядок важен — из него строится и сетка кнопок, и регулярка роутера.
MAIN_MENU_BUTTONS = (
    MENU_JOBS,
    MENU_SETTINGS,
    MENU_SOURCES,
    MENU_STATS,
    MENU_PROFILE,
    MENU_HELP,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard."""
    keyboard = [
        [MENU_JOBS, MENU_SETTINGS],
        [MENU_SOURCES, MENU_STATS],
        [MENU_PROFILE, MENU_HELP],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def sources_keyboard() -> InlineKeyboardMarkup:
    """Sources management keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.PLUS} Добавить источник", callback_data="add_source")],
        [InlineKeyboardButton(f"{P.LIST} Список источников", callback_data="list_sources")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def source_type_keyboard() -> InlineKeyboardMarkup:
    """Source type selection keyboard."""
    keyboard = [
        [InlineKeyboardButton("Kwork", callback_data="source_type_kwork")],
        [InlineKeyboardButton("Telegram канал", callback_data="source_type_telegram")],
        [InlineKeyboardButton(f"{P.CROSS} Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)


def source_actions_keyboard(source_id: int, enabled: bool) -> InlineKeyboardMarkup:
    """Actions for a specific source."""
    toggle_text = f"{P.PAUSE} Отключить" if enabled else f"{P.FORWARD} Включить"
    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data=f"toggle_source_{source_id}")],
        [InlineKeyboardButton(f"{P.TRASH} Удалить", callback_data=f"delete_source_{source_id}")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="list_sources")]
    ]
    return InlineKeyboardMarkup(keyboard)


def vacancy_keyboard(kwork_id: str) -> InlineKeyboardMarkup:
    """Actions for a vacancy."""
    keyboard = [
        [InlineKeyboardButton(f"{P.CHECK} Подходит", callback_data=f"vacancy_suitable_{kwork_id}")],
        [InlineKeyboardButton(f"{P.CROSS} Не подходит", callback_data=f"vacancy_skip_{kwork_id}")],
        [InlineKeyboardButton(f"{P.COMMENT} Сгенерировать отклик", callback_data=f"vacancy_generate_{kwork_id}")],
        [InlineKeyboardButton(f"{P.BAN} В чёрный список", callback_data=f"vacancy_blacklist_{kwork_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def quick_vacancy_actions_keyboard(
    kwork_id: str,
    priority: str = "low",
) -> InlineKeyboardMarkup:
    """Quick actions shown directly in vacancy notification.

    Args:
        kwork_id: Project ID for callback data.
        priority: 'high', 'medium', or 'low'.
    """
    keyboard = []

    # Row 1: main actions
    row1 = [
        InlineKeyboardButton(f"{P.COMMENT} Отклик", callback_data=f"vacancy_generate_{kwork_id}"),
        InlineKeyboardButton(f"{P.EYES} Подробнее", callback_data=f"vacancy_detail_{kwork_id}"),
    ]
    keyboard.append(row1)

    # Row 2: navigation + high-priority quick send
    row2 = [
        InlineKeyboardButton(f"{P.HOURGLASS} Отложить", callback_data=f"vacancy_defer_{kwork_id}"),
        InlineKeyboardButton(f"{P.SKIP} Пропустить", callback_data=f"vacancy_skip_{kwork_id}"),
    ]
    if priority == "high":
        row2.insert(0, InlineKeyboardButton(f"{P.ROCKET} Отправить", callback_data=f"vacancy_send_{kwork_id}"))
    keyboard.append(row2)

    # Row 3: destructive
    row3 = [
        InlineKeyboardButton(f"{P.BAN} В чёрный список", callback_data=f"vacancy_blacklist_{kwork_id}"),
    ]
    keyboard.append(row3)

    return InlineKeyboardMarkup(keyboard)


def response_keyboard(response_id: int, kwork_id: str) -> InlineKeyboardMarkup:
    """Actions for a generated response."""
    keyboard = [
        [InlineKeyboardButton(f"{P.LIST} Показать текст", callback_data=f"response_copy_{response_id}")],
        [InlineKeyboardButton(f"{P.CHECK} Отправить сейчас", callback_data=f"response_send_{response_id}")],
        [InlineKeyboardButton(f"{P.EDIT} Отредактировать", callback_data=f"response_edit_{response_id}")],
        [InlineKeyboardButton(f"{P.RELOAD} Сгенерировать заново", callback_data=f"vacancy_generate_{kwork_id}")],
        [InlineKeyboardButton(f"{P.HOURGLASS} Отложить", callback_data=f"response_defer_{response_id}")],
        [InlineKeyboardButton(f"{P.CROSS} Отменить", callback_data=f"response_cancel_{response_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def settings_keyboard() -> InlineKeyboardMarkup:
    """Settings menu keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.NOTE} Промпт для анализа", callback_data="settings_analysis_prompt")],
        [InlineKeyboardButton(f"{P.COMMENT} Промпт для откликов", callback_data="settings_response_prompt")],
        [InlineKeyboardButton(f"{P.MONEY} Диапазон бюджета", callback_data="settings_budget")],
        [InlineKeyboardButton(f"{P.TIMER} Кулдаун рассылки", callback_data="settings_cooldown")],
        [InlineKeyboardButton(f"{P.SEARCH} Фильтры", callback_data="settings_filters")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def filters_settings_keyboard() -> InlineKeyboardMarkup:
    """Filter settings keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.SCROLL} Белый список слов", callback_data="settings_whitelist")],
        [InlineKeyboardButton(f"{P.BAN} Чёрный список слов", callback_data="settings_blacklist")],
        [InlineKeyboardButton(f"{P.STAR} Мин. рейтинг заказчика", callback_data="settings_min_rating")],
        [InlineKeyboardButton(f"{P.CHART} Макс. предложений", callback_data="settings_max_proposals")],
        [InlineKeyboardButton(f"{P.ROBOT} Авто-режим", callback_data="settings_auto_mode")],
        [InlineKeyboardButton(f"{P.PREV} Назад к настройкам", callback_data="settings_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def profile_keyboard() -> InlineKeyboardMarkup:
    """Freelancer profile keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.NOTE} Навыки", callback_data="profile_skills")],
        [InlineKeyboardButton(f"{P.CALENDAR} Опыт (лет)", callback_data="profile_experience")],
        [InlineKeyboardButton(f"{P.FOLDER} Категории", callback_data="profile_categories")],
        [InlineKeyboardButton(f"{P.MONEY} Ставка/час", callback_data="profile_hourly_rate")],
        [InlineKeyboardButton(f"{P.SPARKLE} Сильные стороны", callback_data="profile_strong_sides")],
        [InlineKeyboardButton(f"{P.DOC} О себе", callback_data="profile_bio")],
        [InlineKeyboardButton(f"{P.LINK} Портфолио", callback_data="profile_portfolio")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def auto_mode_keyboard() -> InlineKeyboardMarkup:
    """Auto mode settings."""
    keyboard = [
        [InlineKeyboardButton(f"{P.FORWARD} Включить авто-режим", callback_data="auto_mode_on")],
        [InlineKeyboardButton(f"{P.PAUSE} Выключить авто-режим", callback_data="auto_mode_off")],
        [InlineKeyboardButton(f"{P.TIMER} Задержка (мин)", callback_data="auto_mode_delay")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="settings_filters")]
    ]
    return InlineKeyboardMarkup(keyboard)


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Confirmation keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.CHECK} Да", callback_data=f"confirm_{action}")],
        [InlineKeyboardButton(f"{P.CROSS} Нет", callback_data=f"cancel_{action}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Simple cancel keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.CROSS} Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)


def stats_keyboard() -> InlineKeyboardMarkup:
    """Statistics keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.RELOAD} Обновить", callback_data="refresh_stats")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def kwork_filters_keyboard() -> InlineKeyboardMarkup:
    """Kwork filters menu keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.ROBOT} AI-дружественные", callback_data="kwork_ai_friendly")],
        [InlineKeyboardButton(f"{P.BRIEFCASE} Простые задачи", callback_data="kwork_simple_tasks")],
        [InlineKeyboardButton(f"{P.MONEY} Фильтр по бюджету", callback_data="kwork_filter_budget")],
        [InlineKeyboardButton(f"{P.TIMER} Фильтр по срокам", callback_data="kwork_filter_deadline")],
        [InlineKeyboardButton(f"{P.LABEL} Фильтр по навыкам", callback_data="kwork_filter_skills")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def ai_friendly_filter_keyboard() -> InlineKeyboardMarkup:
    """AI-friendly filter settings keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.CHECK} Включить", callback_data="kwork_ai_enable")],
        [InlineKeyboardButton(f"{P.CROSS} Выключить", callback_data="kwork_ai_disable")],
        [InlineKeyboardButton(f"{P.TARGET} ИИ-генерация", callback_data="ai_task_type_generate")],
        [InlineKeyboardButton(f"{P.LAPTOP} Вайб-кодинг", callback_data="ai_task_type_vibe")],
        [InlineKeyboardButton(f"{P.FLASK} Авто-тестирование", callback_data="ai_task_type_test")],
        [InlineKeyboardButton(f"{P.PREV} Назад к фильтрам", callback_data="kwork_filters_back")]
    ]
    return InlineKeyboardMarkup(keyboard)


def tg_analysis_keyboard() -> InlineKeyboardMarkup:
    """Telegram analysis menu keyboard."""
    keyboard = [
        [InlineKeyboardButton(f"{P.CHART} Анализ канала", callback_data="tg_analyze_channel")],
        [InlineKeyboardButton(f"{P.TARGET} Поиск заказов", callback_data="tg_search_jobs")],
        [InlineKeyboardButton(f"{P.GRAPH} Тренды и активность", callback_data="tg_analyze_trends")],
        [InlineKeyboardButton(f"{P.ROBOT} AI-анализ", callback_data="tg_ai_analyze")],
        [InlineKeyboardButton(f"{P.PREV} Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def vacancy_list_keyboard(page: int, total_pages: int, vacancies: list) -> InlineKeyboardMarkup:
    """Keyboard for paginated vacancy list."""
    keyboard = []

    # Navigation row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(f"{P.PREV} Назад", callback_data=f"vacancy_page_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"{P.DOC} {page}/{total_pages}", callback_data="vacancy_page_info"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(f"Вперед {P.FORWARD}", callback_data=f"vacancy_page_{page+1}"))
    keyboard.append(nav_row)

    # Vacancy buttons (limit to 5 per page)
    for vacancy in vacancies[:5]:
        keyboard.append([
            InlineKeyboardButton(
                f"{vacancy.title[:40]}..." if len(vacancy.title) > 40 else vacancy.title,
                callback_data=f"vacancy_detail_{vacancy.kwork_id}"
            )
        ])

    # Back to menu
    keyboard.append([InlineKeyboardButton(f"{P.PREV} В меню", callback_data="back_to_main")])

    return InlineKeyboardMarkup(keyboard)
