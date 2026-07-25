"""Extraction + proposal generation with guardrails — AGENTS.md §3.2, §3.5–3.6, §6.

Pipeline (§6.2): cheap model extracts strict JSON per listing; the strong
model is called only when the user asks for a proposal. Guardrails (§6.4):
the generator sees ONLY facts from the user's ``PortfolioItem`` records,
low-confidence extraction flags the project for manual review, and the
output is validated (length, clichés, ending, fabricated-experience checks).

Prompts are versioned files in ``prompts/`` (§6.3) — not hardcoded.
"""
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from core.llm import LLMError, OpenRouterClient
from core.models import PortfolioItem, Project
from services.logger_config import get_logger

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

MIN_WORDS = 80
MAX_WORDS = 150

CLICHES: Tuple[str, ...] = (
    "здравствуйте, увидел ваш проект",
    "увидел ваш проект",
    "увидела ваш проект",
    "заинтересовал ваш проект",
    "меня заинтересовал ваш проект",
    "готов выполнить ваш заказ",
    "выполню качественно и в срок",
    "быстро и качественно",
    "имею большой опыт",
    "большой опыт работы",
    "обращайтесь, не пожалеете",
)

CTA_MARKERS: Tuple[str, ...] = (
    "предлага",
    "давайте",
    "готов обсудить",
    "готова обсудить",
    "могу приступить",
    "созвон",
    "напишите",
    "расскажите",
    "пришлите",
    "уточните",
    "покажу",
    "начнём",
    "начнем",
)

TONES: Dict[str, str] = {
    "neutral": "",
    "formal": "Тон: сдержанный, деловой, на «вы».",
    "friendly": "Тон: дружелюбный, живой, но профессиональный.",
    "expert": "Тон: уверенный эксперт, коротко и по делу.",
}

_EXPERIENCE_CLAIM_RE = re.compile(
    r"(\d{1,2})\s*(?:лет|год[а-я]*)\s+(?:опыт|стаж)|опыт[а-я]*\s+(\d{1,2})\s*(?:лет|год)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class GuardrailError(Exception):
    """Raised when generation cannot proceed safely (§6.4)."""


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Load a versioned prompt template from ``prompts/`` (§6.3)."""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Extraction (§3.2, §6.3)
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """Structured data extracted from a raw listing (§3.2)."""

    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    currency: str = "RUB"
    deadline_days: Optional[int] = None
    required_skills: List[str] = field(default_factory=list)
    client_red_flags: List[str] = field(default_factory=list)
    summary: str = ""
    needs_manual_review: bool = False


def _parse_extraction_json(raw: str) -> ExtractionResult:
    """Parse the strict-JSON extraction output; raise ValueError if invalid."""
    cleaned = _JSON_FENCE_RE.sub("", raw.strip()).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("extraction output is not a JSON object")

    def _opt_int(value: object) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("boolean is not a number")
        if isinstance(value, (int, float)):
            return int(value)
        raise ValueError(f"expected number, got {type(value).__name__}")

    def _str_list(value: object) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("expected list of strings")
        return [str(v) for v in value]

    return ExtractionResult(
        budget_min=_opt_int(data.get("budget_min")),
        budget_max=_opt_int(data.get("budget_max")),
        currency=str(data.get("currency") or "RUB"),
        deadline_days=_opt_int(data.get("deadline_days")),
        required_skills=_str_list(data.get("required_skills")),
        client_red_flags=_str_list(data.get("client_red_flags")),
        summary=str(data.get("summary") or ""),
    )


async def extract_listing(
    text: str,
    client: OpenRouterClient,
    model: str,
) -> ExtractionResult:
    """Extract structured data from a raw listing via the cheap model.

    Low confidence (invalid JSON after one retry, or no budget found) marks
    the result ``needs_manual_review`` per §6.4.
    """
    system = load_prompt("extraction_v1")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text[:6000]},
    ]
    for attempt in (1, 2):
        try:
            raw = await client.chat(
                messages, model=model, temperature=0.0, max_tokens=500, json_mode=True
            )
            result = _parse_extraction_json(raw)
            if result.budget_min is None and result.budget_max is None:
                result.needs_manual_review = True
            return result
        except (LLMError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "extraction.attempt_failed", attempt=attempt, error=str(exc)
            )
            messages.append(
                {"role": "user", "content": "Верни строго JSON по схеме, без текста."}
            )
    return ExtractionResult(needs_manual_review=True)


def fallback_extraction(project: Project) -> ExtractionResult:
    """Deterministic no-LLM extraction from parser-provided fields.

    Used when no LLM key is configured (MVP roadmap: эвристический режим).
    """
    result = ExtractionResult(
        budget_min=project.budget_min,
        budget_max=project.budget_max,
        currency=project.currency or "RUB",
        summary=(project.title or "")[:200],
    )
    if result.budget_min is None and result.budget_max is None:
        result.needs_manual_review = True
    return result


# ---------------------------------------------------------------------------
# Portfolio case selection (§3.6)
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^\wа-яё+#-]+", text.casefold()) if len(t) > 2}


def select_relevant_cases(
    items: Sequence[PortfolioItem],
    required_skills: Sequence[str],
    project_text: str = "",
    k: int = 3,
) -> List[PortfolioItem]:
    """Pick the 2–3 most relevant portfolio cases (§3.6).

    Ranks by tag/skill overlap plus token overlap with the project text.
    Never creates new cases — only reorders existing ones.
    """
    if not items:
        return []
    required = _norm_set(required_skills)
    project_tokens = _tokens(project_text)

    def score(item: PortfolioItem) -> float:
        tags = _norm_set(item.tags or [])
        tag_hits = len(
            {r for r in required if r in tags or any(r in t or t in r for t in tags)}
        )
        text_hits = len(_tokens(f"{item.title} {item.description}") & project_tokens)
        return tag_hits * 3.0 + text_hits * 0.5

    ranked = sorted(items, key=score, reverse=True)
    return list(ranked[: max(1, k)])


def _norm_set(values: Sequence[str]) -> set:
    return {v.strip().casefold() for v in values if v and v.strip()}


def render_portfolio_cases(items: Sequence[PortfolioItem]) -> str:
    """Serialize portfolio cases for prompt injection (§6.4: only these facts)."""
    blocks = []
    for item in items:
        tags = ", ".join(item.tags or [])
        block = f"— {item.title}: {item.description}"
        if tags:
            block += f" (теги: {tags})"
        if item.media_url:
            block += f" [{item.media_url}]"
        blocks.append(block)
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Guardrail validation (§6.4)
# ---------------------------------------------------------------------------


def validate_proposal(text: str, portfolio_items: Sequence[PortfolioItem]) -> List[str]:
    """Validate a proposal against §3.5/§6.4 rules.

    Returns:
        A list of human-readable violations (empty = clean).
    """
    violations: List[str] = []
    words = len(re.findall(r"\S+", text))
    if words < MIN_WORDS:
        violations.append(f"length: {words} слов — меньше {MIN_WORDS}")
    elif words > MAX_WORDS:
        violations.append(f"length: {words} слов — больше {MAX_WORDS}")

    lowered = text.casefold()
    for cliche in CLICHES:
        if cliche in lowered:
            violations.append(f"cliche: «{cliche}»")

    stripped = text.rstrip()
    ends_with_question = stripped.endswith("?")
    tail = stripped[-220:].casefold()
    has_cta = any(marker in tail for marker in CTA_MARKERS)
    if not ends_with_question and not has_cta:
        violations.append("ending: нет вопроса или предложения следующего шага")

    corpus = " ".join(
        f"{i.title} {i.description} {' '.join(i.tags or [])} {i.media_url or ''}"
        for i in portfolio_items
    ).casefold()

    for match in _EXPERIENCE_CLAIM_RE.finditer(text):
        number = match.group(1) or match.group(2)
        if number and number not in corpus:
            violations.append(
                f"fabrication: заявлен опыт «{number} лет», которого нет в портфолио"
            )

    for url in _URL_RE.findall(text):
        if url.rstrip('.,;:!?)') .casefold() not in corpus:
            violations.append(f"fabrication: ссылка не из портфолио — {url}")

    return violations


# ---------------------------------------------------------------------------
# Proposal generation (§3.5)
# ---------------------------------------------------------------------------


@dataclass
class GenerationResult:
    """Outcome of proposal generation."""

    text: str
    violations: List[str] = field(default_factory=list)
    attempts: int = 1


async def generate_proposal(
    project_text: str,
    portfolio_items: Sequence[PortfolioItem],
    client: OpenRouterClient,
    model: str,
    tone: str = "neutral",
    required_skills: Sequence[str] = (),
) -> GenerationResult:
    """Generate a personalized proposal with guardrails (§3.5, §6.4).

    Raises:
        GuardrailError: When the user has no portfolio items — the portfolio
            is the only allowed source of facts (§2.4), so generation refuses
            rather than inventing experience.
    """
    if not portfolio_items:
        raise GuardrailError(
            "Портфолио пусто — добавьте хотя бы один кейс (/portfolio). "
            "Отклик не может ссылаться на выдуманный опыт."
        )
    cases = select_relevant_cases(
        portfolio_items, required_skills, project_text=project_text
    )
    system = load_prompt("proposal_v1").format(
        portfolio_cases=render_portfolio_cases(cases),
        project_text=project_text[:4000],
    )
    tone_note = TONES.get(tone, "")
    if tone_note:
        system = f"{system}\n{tone_note}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Напиши отклик."},
    ]
    best_text = ""
    best_violations: List[str] = ["generation: пустой ответ модели"]
    attempts = 0
    for attempt in (1, 2):
        attempts = attempt
        text = (await client.chat(messages, model=model, temperature=0.7)).strip()
        violations = validate_proposal(text, portfolio_items)
        if len(violations) < len(best_violations) or not best_text:
            best_text, best_violations = text, violations
        if not violations:
            break
        messages.append({"role": "assistant", "content": text})
        messages.append(
            {
                "role": "user",
                "content": "Перепиши отклик, исправив: " + "; ".join(violations),
            }
        )
    logger.info(
        "generation.proposal_done",
        attempts=attempts,
        violations=len(best_violations),
    )
    return GenerationResult(
        text=best_text, violations=best_violations, attempts=attempts
    )


def render_template_proposal(
    project_title: str,
    portfolio_items: Sequence[PortfolioItem],
    budget_line: Optional[str] = None,
) -> str:
    """Deterministic template proposal for the Basic tier (§7, roadmap MVP).

    Uses only portfolio facts; the user edits it manually before sending.
    """
    top = select_relevant_cases(portfolio_items, (), project_title, k=1)
    case_line = (
        f"Похожая задача уже была в моей практике: «{top[0].title}» — {top[0].description[:160]}."
        if top
        else "Опыт и примеры работ пришлю по запросу."
    )
    budget_part = f" Ориентир по бюджету у вас указан ({budget_line})." if budget_line else ""
    return (
        f"Откликаюсь на задачу «{project_title}».\n\n"
        f"{case_line}{budget_part}\n\n"
        "Чтобы назвать точные сроки и стоимость, уточните, пожалуйста: "
        "какой результат для вас приоритетен в первую очередь и есть ли готовые материалы?"
    )


async def generate_portfolio_intro(
    portfolio_items: Sequence[PortfolioItem],
    project_text: str,
    client: OpenRouterClient,
    model: str,
    required_skills: Sequence[str] = (),
) -> str:
    """Generate one adapted intro line from real cases (§3.6)."""
    cases = select_relevant_cases(
        portfolio_items, required_skills, project_text=project_text
    )
    if not cases:
        raise GuardrailError("Нет кейсов портфолио для адаптации.")
    system = load_prompt("portfolio_intro_v1").format(
        portfolio_cases=render_portfolio_cases(cases),
        project_text=project_text[:2000],
    )
    text = await client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "Дай вводную фразу."},
        ],
        model=model,
        temperature=0.5,
        max_tokens=120,
    )
    return text.strip().strip('"«»')
