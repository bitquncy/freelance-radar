"""HTML cards and inline keyboards for V2 notifications."""
from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.handlers.v2.common import esc
from core.crm import STAGE_TITLES, allowed_next_stages
from core.models import (
    Client,
    PipelineStage,
    Project,
    ProjectAnalysis,
    Proposal,
    Reminder,
)
from core.scoring import TrafficLight

SOURCE_TITLES = {
    "kwork": "Kwork",
    "fl_ru": "FL.ru",
    "weblancer": "Weblancer",
    "tg_channel": "Telegram",
    "upwork": "Upwork",
}

STAGE_EMOJI = {
    PipelineStage.NEW_LEAD: "\U0001f195",
    PipelineStage.PROPOSAL_SENT: "\U0001f4e8",
    PipelineStage.NEGOTIATION: "\U0001f4ac",
    PipelineStage.WON: "\U0001f3af",
    PipelineStage.LOST: "❌",
    PipelineStage.IN_PROGRESS: "\U0001f6e0",
    PipelineStage.COMPLETED: "✅",
    PipelineStage.REPEAT_CLIENT: "\U0001f501",
}


def _budget_line(project: Project) -> str:
    if project.budget_min and project.budget_max:
        return f"{project.budget_min}–{project.budget_max} {project.currency}"
    value = project.budget_max or project.budget_min
    if value:
        return f"{value} {project.currency}"
    return project.budget_raw or "не указан"


def project_card(project: Project, analysis: Optional[ProjectAnalysis]) -> str:
    """Render the new-project notification card (§3.3–3.4 outputs)."""
    source = SOURCE_TITLES.get(project.source.value, project.source.value)
    lines = [
        f"<b>{esc(project.title)}</b>",
        f"\U0001f4e1 {esc(source)} · \U0001f4b0 {esc(_budget_line(project))}",
    ]
    if analysis is not None:
        if analysis.needs_manual_review:
            lines.append("⚠️ <i>Требует ручной проверки (бюджет не определён)</i>")
        else:
            if analysis.win_probability is not None:
                lines.append(
                    f"\U0001f3af Вероятность получить заказ: <b>{analysis.win_probability:.0f}%</b>"
                )
            if analysis.profitability_index is not None:
                light = TrafficLight.GREEN
                if analysis.profitability_index < 0.8:
                    light = TrafficLight.RED
                elif analysis.profitability_index <= 1.2:
                    light = TrafficLight.YELLOW
                lines.append(
                    f"{light.emoji} Выгодность: <b>{analysis.profitability_index:.2f}</b>"
                    f" (~{analysis.effective_hourly_rate:.0f} ₽/ч, "
                    f"чистыми ~{analysis.net_payout:.0f} ₽)"
                )
        if analysis.client_red_flags:
            flags = ", ".join(esc(f) for f in analysis.client_red_flags[:3])
            lines.append(f"\U0001f6a9 Красные флаги: {flags}")
        if analysis.summary:
            lines.append(f"\U0001f4dd {esc(analysis.summary[:200])}")
    # Only http(s) links: a scraped URL with an exotic scheme would make
    # Telegram reject the whole message (silent notification loss).
    if project.url and project.url.startswith(("http://", "https://")):
        lines.append(f'<a href="{esc(project.url)}">Открыть заказ</a>')
    return "\n".join(lines)


def project_card_keyboard(project_id: int) -> InlineKeyboardMarkup:
    """Actions under a project card."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✍️ Отклик", callback_data=f"v2p:gen:{project_id}"
                ),
                InlineKeyboardButton(
                    "\U0001f9e9 Кейсы под заказ",
                    callback_data=f"v2p:cases:{project_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f648 Скрыть", callback_data=f"v2p:hide:{project_id}"
                )
            ],
        ]
    )


def proposal_card(proposal: Proposal, project: Optional[Project] = None) -> str:
    """Render a proposal draft/sent card with guardrail warnings (§6.4)."""
    status_titles = {"draft": "Черновик", "edited": "Отредактирован", "sent": "Отправлен"}
    mode_titles = {"ai": "AI", "template": "Шаблон"}
    lines = []
    if project is not None:
        lines.append(f"<b>Отклик: {esc(project.title[:80])}</b>")
    lines.append(
        f"Статус: {status_titles.get(proposal.status.value, proposal.status.value)}"
        f" · Режим: {mode_titles.get(proposal.mode.value, proposal.mode.value)}"
    )
    lines.append("")
    lines.append(esc(proposal.generated_text))
    if proposal.violations:
        lines.append("")
        lines.append("⚠️ <i>Проверьте перед отправкой:</i>")
        for violation in proposal.violations[:5]:
            lines.append(f"• <i>{esc(violation)}</i>")
    return "\n".join(lines)


def proposal_keyboard(proposal_id: int, ai_enabled: bool) -> InlineKeyboardMarkup:
    """Actions under a proposal draft."""
    rows = [
        [
            InlineKeyboardButton(
                "\U0001f4e4 Отправлено", callback_data=f"v2p:send:{proposal_id}"
            ),
            InlineKeyboardButton(
                "✏️ Редактировать", callback_data=f"v2p:edit:{proposal_id}"
            ),
        ]
    ]
    if ai_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    "\U0001f501 Ещё вариант", callback_data=f"v2p:regen:{proposal_id}"
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def reminder_card(client: Client, reminder: Reminder) -> str:
    """Render a follow-up reminder (§3.8)."""
    return (
        f"⏰ <b>Напоминание</b>\n"
        f"Клиент: {esc(client.name)}\n"
        f"Этап: {STAGE_TITLES[client.pipeline_stage]}\n\n"
        f"{esc(reminder.message)}"
    )


def reminder_keyboard(reminder_id: int, client_id: int) -> InlineKeyboardMarkup:
    """One-tap actions per §3.8: написать сейчас / отложить."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✍️ Написать сейчас",
                    callback_data=f"v2r:write:{reminder_id}:{client_id}",
                ),
                InlineKeyboardButton(
                    "⏳ Отложить на сутки",
                    callback_data=f"v2r:snooze:{reminder_id}",
                ),
            ]
        ]
    )


def client_card(client: Client, interactions: List[str]) -> str:
    """Render a CRM client card (§3.7)."""
    lines = [
        f"{STAGE_EMOJI[client.pipeline_stage]} <b>{esc(client.name)}</b>",
        f"Этап: <b>{STAGE_TITLES[client.pipeline_stage]}</b>",
    ]
    if client.last_contact_at is not None:
        lines.append(f"Последний контакт: {client.last_contact_at:%d.%m.%Y %H:%M}")
    if client.notes:
        lines.append(f"\U0001f4dd Заметки: {esc(client.notes[:300])}")
    if interactions:
        lines.append("")
        lines.append("<i>Последние события:</i>")
        for entry in interactions:
            lines.append(f"• {esc(entry)}")
    return "\n".join(lines)


def client_keyboard(client: Client) -> InlineKeyboardMarkup:
    """Stage-transition buttons limited to §3.7-allowed moves."""
    rows = []
    stage_row = [
        InlineKeyboardButton(
            f"➡️ {STAGE_TITLES[stage]}",
            callback_data=f"v2c:stage:{client.id}:{stage.value}",
        )
        for stage in allowed_next_stages(client.pipeline_stage)
    ]
    if stage_row:
        rows.append(stage_row)
    rows.append(
        [
            InlineKeyboardButton(
                "\U0001f4dd Заметка", callback_data=f"v2c:note:{client.id}"
            ),
            InlineKeyboardButton("⬅️ К списку", callback_data="v2c:list"),
        ]
    )
    return InlineKeyboardMarkup(rows)
