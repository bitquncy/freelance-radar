"""Keyboard layouts for the Telegram bot."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard."""
    keyboard = [
        ["📋 Вакансии", "⚙️ Настройки"],
        ["📡 Источники", "📊 Статистика"],
        ["👤 Профиль", "❓ Помощь"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def sources_keyboard() -> InlineKeyboardMarkup:
    """Sources management keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить источник", callback_data="add_source")],
        [InlineKeyboardButton("📋 Список источников", callback_data="list_sources")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def source_type_keyboard() -> InlineKeyboardMarkup:
    """Source type selection keyboard."""
    keyboard = [
        [InlineKeyboardButton("Kwork", callback_data="source_type_kwork")],
        [InlineKeyboardButton("Telegram канал", callback_data="source_type_telegram")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)


def source_actions_keyboard(source_id: int, enabled: bool) -> InlineKeyboardMarkup:
    """Actions for a specific source."""
    toggle_text = "⏸ Отключить" if enabled else "▶️ Включить"
    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data=f"toggle_source_{source_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_source_{source_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="list_sources")]
    ]
    return InlineKeyboardMarkup(keyboard)


def vacancy_keyboard(kwork_id: str) -> InlineKeyboardMarkup:
    """Actions for a vacancy."""
    keyboard = [
        [InlineKeyboardButton("✅ Подходит", callback_data=f"vacancy_suitable_{kwork_id}")],
        [InlineKeyboardButton("❌ Не подходит", callback_data=f"vacancy_skip_{kwork_id}")],
        [InlineKeyboardButton("💬 Сгенерировать отклик", callback_data=f"vacancy_generate_{kwork_id}")],
        [InlineKeyboardButton("🚫 В чёрный список", callback_data=f"vacancy_blacklist_{kwork_id}")]
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
        InlineKeyboardButton("💬 Отклик", callback_data=f"vacancy_generate_{kwork_id}"),
        InlineKeyboardButton("👀 Подробнее", callback_data=f"vacancy_detail_{kwork_id}"),
    ]
    keyboard.append(row1)

    # Row 2: navigation + high-priority quick send
    row2 = [
        InlineKeyboardButton("⏳ Отложить", callback_data=f"vacancy_defer_{kwork_id}"),
        InlineKeyboardButton("⏭ Пропустить", callback_data=f"vacancy_skip_{kwork_id}"),
    ]
    if priority == "high":
        row2.insert(0, InlineKeyboardButton("🚀 Отправить", callback_data=f"vacancy_send_{kwork_id}"))
    keyboard.append(row2)

    # Row 3: destructive
    row3 = [
        InlineKeyboardButton("🚫 В чёрный список", callback_data=f"vacancy_blacklist_{kwork_id}"),
    ]
    keyboard.append(row3)

    return InlineKeyboardMarkup(keyboard)


def response_keyboard(response_id: int, kwork_id: str) -> InlineKeyboardMarkup:
    """Actions for a generated response."""
    keyboard = [
        [InlineKeyboardButton("📋 Показать текст", callback_data=f"response_copy_{response_id}")],
        [InlineKeyboardButton("✅ Отправить сейчас", callback_data=f"response_send_{response_id}")],
        [InlineKeyboardButton("✏️ Отредактировать", callback_data=f"response_edit_{response_id}")],
        [InlineKeyboardButton("🔄 Сгенерировать заново", callback_data=f"vacancy_generate_{kwork_id}")],
        [InlineKeyboardButton("⏳ Отложить", callback_data=f"response_defer_{response_id}")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"response_cancel_{response_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def settings_keyboard() -> InlineKeyboardMarkup:
    """Settings menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("📝 Промпт для анализа", callback_data="settings_analysis_prompt")],
        [InlineKeyboardButton("💬 Промпт для откликов", callback_data="settings_response_prompt")],
        [InlineKeyboardButton("💰 Диапазон бюджета", callback_data="settings_budget")],
        [InlineKeyboardButton("⏱ Кулдаун рассылки", callback_data="settings_cooldown")],
        [InlineKeyboardButton("🔍 Фильтры", callback_data="settings_filters")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def filters_settings_keyboard() -> InlineKeyboardMarkup:
    """Filter settings keyboard."""
    keyboard = [
        [InlineKeyboardButton("📜 Белый список слов", callback_data="settings_whitelist")],
        [InlineKeyboardButton("🚫 Чёрный список слов", callback_data="settings_blacklist")],
        [InlineKeyboardButton("⭐ Мин. рейтинг заказчика", callback_data="settings_min_rating")],
        [InlineKeyboardButton("📊 Макс. предложений", callback_data="settings_max_proposals")],
        [InlineKeyboardButton("🤖 Авто-режим", callback_data="settings_auto_mode")],
        [InlineKeyboardButton("◀️ Назад к настройкам", callback_data="settings_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def profile_keyboard() -> InlineKeyboardMarkup:
    """Freelancer profile keyboard."""
    keyboard = [
        [InlineKeyboardButton("📝 Навыки", callback_data="profile_skills")],
        [InlineKeyboardButton("📅 Опыт (лет)", callback_data="profile_experience")],
        [InlineKeyboardButton("📂 Категории", callback_data="profile_categories")],
        [InlineKeyboardButton("💰 Ставка/час", callback_data="profile_hourly_rate")],
        [InlineKeyboardButton("🌟 Сильные стороны", callback_data="profile_strong_sides")],
        [InlineKeyboardButton("📄 О себе", callback_data="profile_bio")],
        [InlineKeyboardButton("🔗 Портфолио", callback_data="profile_portfolio")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def auto_mode_keyboard() -> InlineKeyboardMarkup:
    """Auto mode settings."""
    keyboard = [
        [InlineKeyboardButton("▶️ Включить авто-режим", callback_data="auto_mode_on")],
        [InlineKeyboardButton("⏸ Выключить авто-режим", callback_data="auto_mode_off")],
        [InlineKeyboardButton("⏱ Задержка (мин)", callback_data="auto_mode_delay")],
        [InlineKeyboardButton("◀️ Назад", callback_data="settings_filters")]
    ]
    return InlineKeyboardMarkup(keyboard)


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Confirmation keyboard."""
    keyboard = [
        [InlineKeyboardButton("✅ Да", callback_data=f"confirm_{action}")],
        [InlineKeyboardButton("❌ Нет", callback_data=f"cancel_{action}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Simple cancel keyboard."""
    keyboard = [
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)


def stats_keyboard() -> InlineKeyboardMarkup:
    """Statistics keyboard."""
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_stats")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def kwork_filters_keyboard() -> InlineKeyboardMarkup:
    """Kwork filters menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🤖 AI-дружественные", callback_data="kwork_ai_friendly")],
        [InlineKeyboardButton("💼 Простые задачи", callback_data="kwork_simple_tasks")],
        [InlineKeyboardButton("💰 Фильтр по бюджету", callback_data="kwork_filter_budget")],
        [InlineKeyboardButton("⏱ Фильтр по срокам", callback_data="kwork_filter_deadline")],
        [InlineKeyboardButton("🏷 Фильтр по навыкам", callback_data="kwork_filter_skills")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def ai_friendly_filter_keyboard() -> InlineKeyboardMarkup:
    """AI-friendly filter settings keyboard."""
    keyboard = [
        [InlineKeyboardButton("✅ Включить", callback_data="kwork_ai_enable")],
        [InlineKeyboardButton("❌ Выключить", callback_data="kwork_ai_disable")],
        [InlineKeyboardButton("🎯 ИИ-генерация", callback_data="ai_task_type_generate")],
        [InlineKeyboardButton("💻 Вайб-кодинг", callback_data="ai_task_type_vibe")],
        [InlineKeyboardButton("🧪 Авто-тестирование", callback_data="ai_task_type_test")],
        [InlineKeyboardButton("◀️ Назад к фильтрам", callback_data="kwork_filters_back")]
    ]
    return InlineKeyboardMarkup(keyboard)


def tg_analysis_keyboard() -> InlineKeyboardMarkup:
    """Telegram analysis menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("📊 Анализ канала", callback_data="tg_analyze_channel")],
        [InlineKeyboardButton("🎯 Поиск заказов", callback_data="tg_search_jobs")],
        [InlineKeyboardButton("📈 Тренды и активность", callback_data="tg_analyze_trends")],
        [InlineKeyboardButton("🤖 AI-анализ", callback_data="tg_ai_analyze")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def vacancy_list_keyboard(page: int, total_pages: int, vacancies: list) -> InlineKeyboardMarkup:
    """Keyboard for paginated vacancy list."""
    keyboard = []

    # Navigation row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️ Назад", callback_data=f"vacancy_page_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="vacancy_page_info"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Вперед ▶️", callback_data=f"vacancy_page_{page+1}"))
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
    keyboard.append([InlineKeyboardButton("◀️ В меню", callback_data="back_to_main")])

    return InlineKeyboardMarkup(keyboard)
