"""Тесты иконок: premium tg-emoji в HTML, plain Unicode в кнопках/алертах.

Главный инвариант: Telegram парсит ``<tg-emoji>`` ТОЛЬКО в тексте сообщений
с ``parse_mode="HTML"``. В подписях ``InlineKeyboardButton``, в
``answer(show_alert=True)`` и в описаниях ``BotCommand`` HTML не парсится,
поэтому тег протёк бы пользователю как сырой текст. Тесты ловят такую
регрессию до продакшена.
"""
import pytest

import emoji_config
from emoji_config import (
    BTN_DANGER,
    BTN_NEUTRAL,
    BTN_PRIMARY,
    CUSTOM_EMOJIS,
    E,
    P,
    btn,
    btn_danger,
    btn_neutral,
    btn_primary,
    check_emoji_config,
    emoji,
    danger_button,
    primary_button,
    success_button,
)

TAG = "tg-emoji"


@pytest.fixture()
def premium(monkeypatch):
    """Premium-режим без перезагрузки модуля.

    Именно так это работает в бою: ``E.*`` и :func:`emoji` читают флаг
    при каждом обращении, поэтому reload() не нужен и порядок
    импортов в тестах ничего не ломает.
    """
    monkeypatch.setenv("USE_PREMIUM_EMOJI", "1")
    return emoji_config


class TestPlainDefault:
    def test_plain_mode_is_the_default(self) -> None:
        """Без переменной окружения premium выключен и E == P."""
        assert emoji_config.premium_enabled() is False
        assert E.CHECK == P.CHECK == "✅"
        assert TAG not in E.CHECK

    def test_unknown_name_raises(self) -> None:
        """Опечатка в имени иконки падает сразу, а не в рантайме бота."""
        with pytest.raises(AttributeError):
            E.NO_SUCH_ICON

    def test_unmapped_icon_falls_back_to_unicode(self) -> None:
        """Иконка без ID никогда не ломает сообщение."""
        assert emoji("🧸") == "🧸"

    def test_p_is_always_plain(self) -> None:
        """Все константы P — обычный Unicode без HTML."""
        for name, value in vars(P).items():
            if name.startswith("_") or not isinstance(value, str):
                continue
            assert "<" not in value, name


class TestPremiumMode:
    def test_mapped_icon_becomes_a_tag(self, premium) -> None:
        """С premium иконка из пака превращается в <tg-emoji> с её ID."""
        assert premium.premium_enabled() is True
        result = premium.emoji("✅")
        assert result == (
            f'<tg-emoji emoji-id="{CUSTOM_EMOJIS["✅"]}">✅</tg-emoji>'
        )

    def test_plain_class_stays_plain_in_premium(self, premium) -> None:
        """P остаётся Unicode даже когда premium включён — это его смысл."""
        assert premium.P.CHECK == "✅"
        assert TAG not in premium.P.CHECK
        assert TAG in premium.E.CHECK

    def test_strip_html_emoji_recovers_unicode(self, premium) -> None:
        """Тег можно развернуть обратно для plain-контекстов."""
        assert premium.strip_html_emoji(premium.E.CHECK) == "✅"
        mixed = f"{premium.E.LOCK} Доступ {premium.E.CHECK}"
        assert TAG not in premium.strip_html_emoji(mixed)
        assert "Доступ" in premium.strip_html_emoji(mixed)

    def test_unmapped_icon_still_falls_back(self, premium) -> None:
        assert premium.emoji("🧸") == "🧸"


class TestButtonColors:
    def test_color_markers_are_distinct(self) -> None:
        """Семантика цвета: у каждого назначения свой маркер."""
        assert len({BTN_PRIMARY, BTN_DANGER, BTN_NEUTRAL}) == 3

    def test_btn_composes_color_icon_and_label(self) -> None:
        assert btn("Оплатить", BTN_PRIMARY, P.CARD) == f"{BTN_PRIMARY} {P.CARD} Оплатить"
        assert btn("Назад") == "Назад"

    def test_helpers_apply_their_color(self) -> None:
        assert btn_primary("Да").startswith(BTN_PRIMARY)
        assert btn_danger("Удалить").startswith(BTN_DANGER)
        assert btn_neutral("В меню").startswith(BTN_NEUTRAL)

    def test_labels_never_contain_html(self, premium) -> None:
        """Даже в premium-режиме подпись кнопки остаётся plain."""
        label = premium.btn_primary("Подключить", premium.P.CARD)
        assert TAG not in label

    def test_native_button_styles_and_custom_icons(self) -> None:
        success = success_button("Подключить", icon=P.CARD, callback_data="buy")
        primary = primary_button("Назад", icon=P.BACK, callback_data="back")
        danger = danger_button("Удалить", icon=P.TRASH, callback_data="delete")

        assert success.to_dict()["style"] == "success"
        assert primary.to_dict()["style"] == "primary"
        assert danger.to_dict()["style"] == "danger"
        assert success.to_dict()["icon_custom_emoji_id"] == CUSTOM_EMOJIS[P.CARD]
        assert success.text == "Подключить"
        assert TAG not in success.text


class TestConfigReport:
    def test_report_counts_mapping_and_gaps(self) -> None:
        stats = check_emoji_config()
        assert stats["missing"] == 0  # нет незаполненных ЗАМЕНИТЕ_НА_REAL_ID
        assert stats["total"] == len(CUSTOM_EMOJIS)
        assert stats["ui_icons"] > 0
        # Иконки без ID допустимы (fallback), но список должен быть честным.
        assert isinstance(stats["unmapped_ui_icons"], list)


class TestNoTagLeaksIntoPlainContexts:
    """Сквозная защита: ни одна кнопка/алерт не содержит HTML-тега."""

    def _all_button_labels(self, module_premium) -> list:
        from bot.handlers.v2.cards import project_card_keyboard, proposal_keyboard
        from bot.handlers.v2.common import paywall_keyboard
        from bot.handlers.v2.menu import main_menu_keyboard
        from bot.handlers.v2.subscription import _tariff_keyboard
        from bot.keyboards import settings_keyboard

        markups = [
            main_menu_keyboard(onboarded=False),
            main_menu_keyboard(onboarded=True),
            paywall_keyboard(),
            _tariff_keyboard(),
            _tariff_keyboard(active=True),
            project_card_keyboard(1),
            proposal_keyboard(1, ai_enabled=True),
            settings_keyboard(),
        ]
        return [
            button.text
            for markup in markups
            for row in markup.inline_keyboard
            for button in row
        ]

    def test_inline_buttons_are_plain(self, premium) -> None:
        for label in self._all_button_labels(premium):
            assert TAG not in label, label

    def test_reply_menu_and_commands_are_plain(self, premium) -> None:
        from bot.handlers.v2 import BOT_COMMANDS
        from bot.keyboards import main_menu_keyboard as legacy_menu

        for row in legacy_menu().keyboard:
            for button in row:
                assert TAG not in button.text
        for command in BOT_COMMANDS:
            assert TAG not in command.description

    def test_alert_text_is_plain(self, premium) -> None:
        from bot.handlers.v2.common import NO_ACCESS_TEXT

        assert TAG not in NO_ACCESS_TEXT
        # Telegram обрезает alert примерно на 200 символах.
        assert len(NO_ACCESS_TEXT) <= 200

    def test_html_messages_do_use_premium(self, premium) -> None:
        """А вот в HTML-тексте premium-иконки обязаны появляться."""
        from bot.handlers.v2.common import paywall_text

        assert TAG in paywall_text()


class TestLegacyMenuStaysRoutable:
    """Подписи reply-меню и матчеры роутера обязаны совпадать.

    Регрессия, возможная при смене иконок: кнопка отрисована с одной
    иконкой, а ``main.py`` сравнивает текст с другой — нажатие молча
    ничего не делает.
    """

    def test_keyboard_is_built_from_the_shared_constants(self) -> None:
        from bot.keyboards import MAIN_MENU_BUTTONS, main_menu_keyboard

        labels = [
            button.text
            for row in main_menu_keyboard().keyboard
            for button in row
        ]
        assert labels == list(MAIN_MENU_BUTTONS)

    def test_router_regex_matches_every_menu_button(self) -> None:
        import re

        from bot.keyboards import MAIN_MENU_BUTTONS

        pattern = "^(?:{})$".format(
            "|".join(re.escape(label) for label in MAIN_MENU_BUTTONS)
        )
        matcher = re.compile(pattern)
        for label in MAIN_MENU_BUTTONS:
            assert matcher.match(label), label
        # И не ловит произвольный текст без иконки.
        assert matcher.match("Вакансии") is None

    def test_menu_labels_have_no_html(self, premium) -> None:
        from bot.keyboards import MAIN_MENU_BUTTONS

        for label in MAIN_MENU_BUTTONS:
            assert TAG not in label
