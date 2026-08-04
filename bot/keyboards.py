"""Keyboard layouts for the Telegram bot."""

from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup

from emoji_config import (
    P,
    btn_danger,
    btn_neutral,
    btn_primary,
    danger_button,
    inline_button,
    primary_button,
    success_button,
)

# Единый источник истины для подписей reply-меню: они же служат
# матчерами входящего текста в ``main.py``. Держать их в одном месте
# обязательно: рассогласование сделало бы кнопки нажатыми-без-реакции.
#
# ReplyKeyboardMarkup не поддерживает нативные ``style``/``icon_custom_emoji_id``
# (Bot API 9.4 стилизует только inline-кнопки), поэтому «цвет» reply-меню —
# цветной маркер BTN_* перед текстом. Маркеры всегда plain Unicode, чтобы не
# ломать матчинг роутера и не протекать HTML-тегами в подписи кнопок.
MENU_JOBS = btn_primary("Вакансии", P.LIST)
MENU_SETTINGS = btn_primary("Настройки", P.SETTINGS)
MENU_SOURCES = btn_primary("Источники", P.RADAR)
MENU_STATS = btn_neutral("Статистика", P.CHART)
MENU_PROFILE = btn_primary("Профиль", P.USER)
MENU_HELP = btn_neutral("Помощь", P.HELP)
MENU_BROADCAST = btn_danger("Рассылка", P.MEGAPHONE)

#: Порядок важен — из него строится и сетка кнопок, и регулярка роутера.
MAIN_MENU_BUTTONS = (
    MENU_JOBS,
    MENU_SETTINGS,
    MENU_SOURCES,
    MENU_STATS,
    MENU_PROFILE,
    MENU_HELP,
    MENU_BROADCAST,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard; native inline styles do not apply here."""
    keyboard = [
        [MENU_JOBS, MENU_SETTINGS],
        [MENU_SOURCES, MENU_STATS],
        [MENU_PROFILE, MENU_HELP],
        [MENU_BROADCAST],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def sources_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                success_button(
                    "Добавить источник", icon=P.PLUS, callback_data="add_source"
                )
            ],
            [
                primary_button(
                    "Список источников", icon=P.LIST, callback_data="list_sources"
                )
            ],
            [primary_button("Назад", icon=P.PREV, callback_data="back_to_main")],
        ]
    )


def source_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [primary_button("Kwork", icon=P.RADAR, callback_data="source_type_kwork")],
            [
                primary_button(
                    "Telegram канал",
                    icon=P.TELEGRAM,
                    callback_data="source_type_telegram",
                )
            ],
            [danger_button("Отмена", icon=P.CROSS, callback_data="cancel")],
        ]
    )


def source_actions_keyboard(source_id: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle = (
        danger_button(
            "Отключить", icon=P.PAUSE, callback_data=f"toggle_source_{source_id}"
        )
        if enabled
        else success_button(
            "Включить", icon=P.FORWARD, callback_data=f"toggle_source_{source_id}"
        )
    )
    return InlineKeyboardMarkup(
        [
            [toggle],
            [
                danger_button(
                    "Удалить", icon=P.TRASH, callback_data=f"delete_source_{source_id}"
                )
            ],
            [primary_button("Назад", icon=P.PREV, callback_data="list_sources")],
        ]
    )


def vacancy_keyboard(kwork_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                success_button(
                    "Подходит",
                    icon=P.CHECK,
                    callback_data=f"vacancy_suitable_{kwork_id}",
                )
            ],
            [
                danger_button(
                    "Не подходит",
                    icon=P.CROSS,
                    callback_data=f"vacancy_skip_{kwork_id}",
                )
            ],
            [
                success_button(
                    "Сгенерировать отклик",
                    icon=P.COMMENT,
                    callback_data=f"vacancy_generate_{kwork_id}",
                )
            ],
            [
                danger_button(
                    "В чёрный список",
                    icon=P.BAN,
                    callback_data=f"vacancy_blacklist_{kwork_id}",
                )
            ],
        ]
    )


def quick_vacancy_actions_keyboard(
    kwork_id: str, priority: str = "low"
) -> InlineKeyboardMarkup:
    row1 = [
        success_button(
            "Отклик", icon=P.COMMENT, callback_data=f"vacancy_generate_{kwork_id}"
        ),
        primary_button(
            "Подробнее", icon=P.EYES, callback_data=f"vacancy_detail_{kwork_id}"
        ),
    ]
    row2 = [
        primary_button(
            "Отложить", icon=P.HOURGLASS, callback_data=f"vacancy_defer_{kwork_id}"
        ),
        danger_button(
            "Пропустить", icon=P.SKIP, callback_data=f"vacancy_skip_{kwork_id}"
        ),
    ]
    if priority == "high":
        row2.insert(
            0,
            success_button(
                "Отправить", icon=P.ROCKET, callback_data=f"vacancy_send_{kwork_id}"
            ),
        )
    return InlineKeyboardMarkup(
        [
            row1,
            row2,
            [
                danger_button(
                    "В чёрный список",
                    icon=P.BAN,
                    callback_data=f"vacancy_blacklist_{kwork_id}",
                )
            ],
        ]
    )


def response_keyboard(response_id: int, kwork_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                primary_button(
                    "Показать текст",
                    icon=P.LIST,
                    callback_data=f"response_copy_{response_id}",
                )
            ],
            [
                success_button(
                    "Отправить сейчас",
                    icon=P.CHECK,
                    callback_data=f"response_send_{response_id}",
                )
            ],
            [
                primary_button(
                    "Отредактировать",
                    icon=P.EDIT,
                    callback_data=f"response_edit_{response_id}",
                )
            ],
            [
                primary_button(
                    "Сгенерировать заново",
                    icon=P.RELOAD,
                    callback_data=f"vacancy_generate_{kwork_id}",
                )
            ],
            [
                primary_button(
                    "Отложить",
                    icon=P.HOURGLASS,
                    callback_data=f"response_defer_{response_id}",
                )
            ],
            [
                danger_button(
                    "Отменить",
                    icon=P.CROSS,
                    callback_data=f"response_cancel_{response_id}",
                )
            ],
        ]
    )


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                primary_button(
                    "Промпт для анализа",
                    icon=P.NOTE,
                    callback_data="settings_analysis_prompt",
                )
            ],
            [
                primary_button(
                    "Промпт для откликов",
                    icon=P.COMMENT,
                    callback_data="settings_response_prompt",
                )
            ],
            [
                primary_button(
                    "Диапазон бюджета", icon=P.MONEY, callback_data="settings_budget"
                )
            ],
            [
                primary_button(
                    "Кулдаун рассылки", icon=P.TIMER, callback_data="settings_cooldown"
                )
            ],
            [
                primary_button(
                    "Фильтры", icon=P.SEARCH, callback_data="settings_filters"
                )
            ],
            [primary_button("Назад", icon=P.PREV, callback_data="back_to_main")],
        ]
    )


def filters_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                primary_button(
                    "Белый список слов",
                    icon=P.SCROLL,
                    callback_data="settings_whitelist",
                )
            ],
            [
                primary_button(
                    "Чёрный список слов", icon=P.BAN, callback_data="settings_blacklist"
                )
            ],
            [
                primary_button(
                    "Мин. рейтинг заказчика",
                    icon=P.STAR,
                    callback_data="settings_min_rating",
                )
            ],
            [
                primary_button(
                    "Макс. предложений",
                    icon=P.CHART,
                    callback_data="settings_max_proposals",
                )
            ],
            [
                primary_button(
                    "Авто-режим", icon=P.ROBOT, callback_data="settings_auto_mode"
                )
            ],
            [
                primary_button(
                    "Назад к настройкам", icon=P.PREV, callback_data="settings_menu"
                )
            ],
        ]
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [primary_button("Навыки", icon=P.NOTE, callback_data="profile_skills")],
            [
                primary_button(
                    "Опыт (лет)", icon=P.CALENDAR, callback_data="profile_experience"
                )
            ],
            [
                primary_button(
                    "Категории", icon=P.FOLDER, callback_data="profile_categories"
                )
            ],
            [
                primary_button(
                    "Ставка/час", icon=P.MONEY, callback_data="profile_hourly_rate"
                )
            ],
            [
                primary_button(
                    "Сильные стороны",
                    icon=P.SPARKLE,
                    callback_data="profile_strong_sides",
                )
            ],
            [primary_button("О себе", icon=P.DOC, callback_data="profile_bio")],
            [
                primary_button(
                    "Портфолио", icon=P.LINK, callback_data="profile_portfolio"
                )
            ],
            [primary_button("Назад", icon=P.PREV, callback_data="back_to_main")],
        ]
    )


def auto_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                success_button(
                    "Включить авто-режим", icon=P.FORWARD, callback_data="auto_mode_on"
                )
            ],
            [
                danger_button(
                    "Выключить авто-режим", icon=P.PAUSE, callback_data="auto_mode_off"
                )
            ],
            [
                primary_button(
                    "Задержка (мин)", icon=P.TIMER, callback_data="auto_mode_delay"
                )
            ],
            [primary_button("Назад", icon=P.PREV, callback_data="settings_filters")],
        ]
    )


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [success_button("Да", icon=P.CHECK, callback_data=f"confirm_{action}")],
            [danger_button("Нет", icon=P.CROSS, callback_data=f"cancel_{action}")],
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[danger_button("Отмена", icon=P.CROSS, callback_data="cancel")]]
    )


def stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [primary_button("Обновить", icon=P.RELOAD, callback_data="refresh_stats")],
            [primary_button("Назад", icon=P.PREV, callback_data="back_to_main")],
        ]
    )


def kwork_filters_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                primary_button(
                    "AI-дружественные", icon=P.ROBOT, callback_data="kwork_ai_friendly"
                )
            ],
            [
                primary_button(
                    "Простые задачи",
                    icon=P.BRIEFCASE,
                    callback_data="kwork_simple_tasks",
                )
            ],
            [
                primary_button(
                    "Фильтр по бюджету",
                    icon=P.MONEY,
                    callback_data="kwork_filter_budget",
                )
            ],
            [
                primary_button(
                    "Фильтр по срокам",
                    icon=P.TIMER,
                    callback_data="kwork_filter_deadline",
                )
            ],
            [
                primary_button(
                    "Фильтр по навыкам",
                    icon=P.LABEL,
                    callback_data="kwork_filter_skills",
                )
            ],
            [primary_button("Назад", icon=P.PREV, callback_data="back_to_main")],
        ]
    )


def ai_friendly_filter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [success_button("Включить", icon=P.CHECK, callback_data="kwork_ai_enable")],
            [
                danger_button(
                    "Выключить", icon=P.CROSS, callback_data="kwork_ai_disable"
                )
            ],
            [
                primary_button(
                    "ИИ-генерация", icon=P.TARGET, callback_data="ai_task_type_generate"
                )
            ],
            [
                primary_button(
                    "Вайб-кодинг", icon=P.LAPTOP, callback_data="ai_task_type_vibe"
                )
            ],
            [
                primary_button(
                    "Авто-тестирование", icon=P.FLASK, callback_data="ai_task_type_test"
                )
            ],
            [
                primary_button(
                    "Назад к фильтрам", icon=P.PREV, callback_data="kwork_filters_back"
                )
            ],
        ]
    )


def tg_analysis_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                primary_button(
                    "Анализ канала", icon=P.CHART, callback_data="tg_analyze_channel"
                )
            ],
            [
                primary_button(
                    "Поиск заказов", icon=P.TARGET, callback_data="tg_search_jobs"
                )
            ],
            [
                primary_button(
                    "Тренды и активность",
                    icon=P.GRAPH,
                    callback_data="tg_analyze_trends",
                )
            ],
            [success_button("AI-анализ", icon=P.ROBOT, callback_data="tg_ai_analyze")],
            [primary_button("Назад", icon=P.PREV, callback_data="back_to_main")],
        ]
    )


def vacancy_list_keyboard(
    page: int, total_pages: int, vacancies: list
) -> InlineKeyboardMarkup:
    nav_row = []
    if page > 1:
        nav_row.append(
            primary_button("Назад", icon=P.PREV, callback_data=f"vacancy_page_{page-1}")
        )
    nav_row.append(
        inline_button(
            f"{page}/{total_pages}", icon=P.DOC, callback_data="vacancy_page_info"
        )
    )
    if page < total_pages:
        nav_row.append(
            primary_button(
                "Вперёд", icon=P.FORWARD, callback_data=f"vacancy_page_{page+1}"
            )
        )
    keyboard = [nav_row]
    for vacancy in vacancies[:5]:
        title = f"{vacancy.title[:40]}..." if len(vacancy.title) > 40 else vacancy.title
        keyboard.append(
            [inline_button(title, callback_data=f"vacancy_detail_{vacancy.kwork_id}")]
        )
    keyboard.append(
        [primary_button("В меню", icon=P.PREV, callback_data="back_to_main")]
    )
    return InlineKeyboardMarkup(keyboard)
