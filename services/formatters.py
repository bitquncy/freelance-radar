"""Shared formatting utilities for vacancy display."""
from db.models import JobVacancy
from constants import Priority, PRIORITY_EMOJI, PRIORITY_MAP, BULLET
from services.text_utils import esc
from emoji_config import E


def get_priority_emoji(priority: str) -> str:
    """Get emoji for priority level."""
    try:
        return PRIORITY_EMOJI.get(Priority(priority), "\u26aa")
    except ValueError:
        return "\u26aa"


def format_vacancy_notification(vacancy: JobVacancy, analysis: dict) -> str:
    """Build a short, structured HTML notification for a vacancy."""
    priority = analysis.get("priority", "low")
    score = analysis.get("score")
    match = analysis.get("match_percentage")

    p_emoji, p_label = PRIORITY_MAP.get(priority, ("\u26aa", "N/A"))

    line1_parts = [f"{p_emoji} <b>{p_label}</b>"]
    if score is not None:
        line1_parts.append(f"Score: <b>{score}</b>/100")
    if match is not None:
        line1_parts.append(f"Match: <b>{match}%</b>")
    line1 = f" {BULLET} ".join(line1_parts)

    line2 = ""
    if vacancy.budget_min and vacancy.budget_max:
        line2 = f"{E.MONEY} <b>{vacancy.budget_min:,} \u2013 {vacancy.budget_max:,} \u20bd</b>"
    elif vacancy.budget:
        line2 = f"{E.MONEY} <b>{esc(vacancy.budget)}</b>"

    metrics = []
    if vacancy.deadline:
        metrics.append(f"\u23f3 {esc(vacancy.deadline)}")
    if vacancy.proposals_count is not None:
        metrics.append(f"{E.CHART} {vacancy.proposals_count} предл.")
    if vacancy.customer_rating is not None:
        rating_str = f"\u2b50 {vacancy.customer_rating}"
        if vacancy.customer_orders:
            rating_str += f" ({vacancy.customer_orders})"
        metrics.append(rating_str)
    elif vacancy.customer_orders:
        metrics.append(f"{E.PACKAGE} {vacancy.customer_orders} заказов")
    line3 = f" {BULLET} ".join(metrics) if metrics else ""

    line4 = f"<b>{esc(vacancy.title)}</b>"

    desc = vacancy.description or ""
    if len(desc) > 200:
        desc = desc[:200].rsplit(" ", 1)[0] + "\u2026"
    line5 = esc(desc)

    line6 = ""
    if vacancy.skills:
        skills = vacancy.skills_list
        if skills:
            line6 = f"<b>{E.TOOLS} \u041d\u0430\u0432\u044b\u043a\u0438:</b> {esc(', '.join(skills[:6]))}"

    url = vacancy.url or ""
    line7 = f'{E.LINK} <a href="{esc(url)}">\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043d\u0430 Kwork</a>'

    parts = [line1]
    if line2:
        parts.append(line2)
    if line3:
        parts.append(line3)
    parts.append("")
    parts.append(line4)
    if line5:
        parts.append(line5)
    if line6:
        parts.append(line6)
    parts.append("")
    parts.append(line7)

    return "\n".join(parts)


def format_vacancy_full(vacancy: JobVacancy) -> str:
    """Format vacancy text with HTML and styling (full detail view)."""
    p_emoji, p_label = PRIORITY_MAP.get(vacancy.ai_priority, ("\u26aa", "N/A"))

    line1_parts = [f"{p_emoji} <b>{p_label}</b>"]
    if vacancy.ai_score is not None:
        line1_parts.append(f"Score: <b>{vacancy.ai_score}</b>/100")
    if vacancy.match_percentage is not None:
        line1_parts.append(f"Match: <b>{vacancy.match_percentage}%</b>")
    line1 = f" {BULLET} ".join(line1_parts)

    line2 = f"<b>{esc(vacancy.title)}</b>"

    line3 = ""
    if vacancy.budget_min and vacancy.budget_max:
        line3 = f"{E.MONEY} <b>{vacancy.budget_min:,} \u2013 {vacancy.budget_max:,} \u20bd</b>"
    elif vacancy.budget:
        line3 = f"{E.MONEY} <b>{esc(vacancy.budget)}</b>"

    metrics = []
    if vacancy.deadline:
        metrics.append(f"\u23f3 {esc(vacancy.deadline)}")
    if vacancy.deadline_days:
        metrics.append(f"{E.CALENDAR} {vacancy.deadline_days} \u0434\u043d.")
    if vacancy.proposals_count is not None:
        metrics.append(f"{E.CHART} {vacancy.proposals_count} предл.")
    if vacancy.customer_rating is not None:
        rating_str = f"\u2b50 {vacancy.customer_rating}"
        if vacancy.customer_orders:
            rating_str += f" ({vacancy.customer_orders} \u0437\u0430\u043a\u0430\u0437\u043e\u0432)"
        metrics.append(rating_str)
    elif vacancy.customer_orders:
        metrics.append(f"{E.PACKAGE} {vacancy.customer_orders} \u0437\u0430\u043a\u0430\u0437\u043e\u0432")
    line4 = f" {BULLET} ".join(metrics) if metrics else ""

    line5 = ""
    if vacancy.category:
        line5 = f"{E.FILES} {esc(vacancy.category)}"
        if vacancy.subcategory:
            line5 += f" \u2192 {esc(vacancy.subcategory)}"

    desc = vacancy.description or ""
    if len(desc) > 400:
        desc = desc[:400].rsplit(" ", 1)[0] + "\u2026"
    line6 = esc(desc)

    line7 = ""
    if vacancy.skills:
        skills = vacancy.skills_list
        if skills:
            line7 = f"<b>{E.TOOLS} \u041d\u0430\u0432\u044b\u043a\u0438:</b> {esc(', '.join(skills[:6]))}"

    line8 = ""
    if vacancy.ai_risks:
        line8 = f"\u26a0\ufe0f \u0420\u0438\u0441\u043a\u0438: {esc(vacancy.ai_risks)}"

    url = vacancy.url or ""
    line9 = f'{E.LINK} <a href="{esc(url)}">\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0437\u0430\u043a\u0430\u0437</a>'
    line10 = f"{E.RADAR} {esc(vacancy.source)} {BULLET} ID: <code>{esc(vacancy.kwork_id)}</code>"

    parts = [line1, line2]
    if line3:
        parts.append(line3)
    if line4:
        parts.append(line4)
    if line5:
        parts.append(line5)
    parts.append("")
    if line6:
        parts.append(line6)
    if line7:
        parts.append(line7)
    if line8:
        parts.append(line8)
    parts.append("")
    parts.append(line9)
    parts.append(line10)

    return "\n".join(parts)
