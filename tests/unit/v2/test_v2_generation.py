"""Extraction + generation guardrail tests — §3.2, §3.5, §6.3–6.4."""

import pytest

from core.generation import (
    GuardrailError,
    extract_listing,
    fallback_extraction,
    generate_portfolio_intro,
    generate_proposal,
    load_prompt,
    render_template_proposal,
    select_relevant_cases,
    validate_proposal,
)
from tests.unit.v2.conftest import GOOD_PROPOSAL, FakeLLM, make_project

EXTRACTION_JSON = (
    '{"budget_min": 20000, "budget_max": 30000, "currency": "RUB",'
    ' "deadline_days": 14, "required_skills": ["python", "telegram"],'
    ' "client_red_flags": ["нет рейтинга"], "summary": "Бот записи"}'
)


class TestPrompts:
    def test_prompts_are_versioned_files(self) -> None:
        """§6.3: prompts live in prompts/, not in code."""
        extraction = load_prompt("extraction_v1")
        proposal = load_prompt("proposal_v1")
        assert "JSON" in extraction
        assert "{portfolio_cases}" in proposal
        assert "{project_text}" in proposal


class TestExtraction:
    async def test_happy_path(self) -> None:
        """Valid strict JSON is parsed into the §3.2 schema."""
        llm = FakeLLM([EXTRACTION_JSON])
        result = await extract_listing("Нужен бот", llm, model="cheap")
        assert result.budget_min == 20000
        assert result.budget_max == 30000
        assert result.deadline_days == 14
        assert result.required_skills == ["python", "telegram"]
        assert result.client_red_flags == ["нет рейтинга"]
        assert result.needs_manual_review is False
        assert llm.calls[0]["json_mode"] is True

    async def test_json_with_code_fences_is_cleaned(self) -> None:
        """Models sometimes wrap JSON in fences — we strip them."""
        llm = FakeLLM([f"```json\n{EXTRACTION_JSON}\n```"])
        result = await extract_listing("t", llm, model="cheap")
        assert result.budget_min == 20000

    async def test_invalid_json_retries_then_flags_manual_review(self) -> None:
        """§6.4: low extraction confidence → manual review flag."""
        llm = FakeLLM(["это не json", "все еще не json"])
        result = await extract_listing("t", llm, model="cheap")
        assert result.needs_manual_review is True
        assert len(llm.calls) == 2

    async def test_missing_budget_flags_manual_review(self) -> None:
        """§6.4: budget not found → manual review."""
        llm = FakeLLM(
            [
                '{"budget_min": null, "budget_max": null, "currency": "RUB",'
                ' "deadline_days": null, "required_skills": [],'
                ' "client_red_flags": [], "summary": "?"}'
            ]
        )
        result = await extract_listing("t", llm, model="cheap")
        assert result.needs_manual_review is True

    def test_fallback_extraction_uses_parser_fields(self) -> None:
        """No-LLM mode reuses parser budgets (MVP heuristic path)."""
        project = make_project()
        result = fallback_extraction(project)
        assert result.budget_min == 20000
        assert result.needs_manual_review is False

        empty = make_project(external_id="e", budget_min=None, budget_max=None)
        assert fallback_extraction(empty).needs_manual_review is True


class TestGuardrails:
    def test_clean_proposal_passes(self, portfolio) -> None:
        """A grounded 80–150-word proposal with a question is clean."""
        assert validate_proposal(GOOD_PROPOSAL, portfolio) == []

    def test_short_proposal_fails_length(self, portfolio) -> None:
        """§3.5: 80–150 words enforced."""
        violations = validate_proposal("Слишком короткий отклик?", portfolio)
        assert any(v.startswith("length") for v in violations)

    def test_cliche_detected(self, portfolio) -> None:
        """§3.5/§6.3: no «увидел ваш проект» boilerplate."""
        text = "Здравствуйте, увидел ваш проект. " + GOOD_PROPOSAL
        violations = validate_proposal(text, portfolio)
        assert any("cliche" in v for v in violations)

    def test_missing_cta_detected(self, portfolio) -> None:
        """§3.5: must end with a question or concrete next step."""
        words = ("слово " * 100).strip() + "."
        violations = validate_proposal(words, portfolio)
        assert any(v.startswith("ending") for v in violations)

    def test_fabricated_experience_detected(self, portfolio) -> None:
        """§6.4: experience years not present in portfolio → violation."""
        text = GOOD_PROPOSAL.replace(
            "Задача с записью клиентов", "У меня 12 лет опыта, и задача"
        )
        violations = validate_proposal(text, portfolio)
        assert any("fabrication" in v for v in violations)

    def test_experience_from_portfolio_allowed(self, portfolio) -> None:
        """Years that ARE in the portfolio (5 лет) are allowed."""
        text = GOOD_PROPOSAL.replace(
            "Задача с записью клиентов", "У меня 5 лет опыта, и задача"
        )
        violations = validate_proposal(text, portfolio)
        assert not any("fabrication" in v for v in violations)

    def test_foreign_url_detected(self, portfolio) -> None:
        """§6.4: links not from the portfolio are flagged."""
        text = GOOD_PROPOSAL + " Примеры: https://example.com/fake"
        violations = validate_proposal(text, portfolio)
        assert any("ссылка" in v for v in violations)


class TestGenerateProposal:
    async def test_empty_portfolio_refuses(self) -> None:
        """§6.4: no portfolio → refuse instead of inventing facts."""
        llm = FakeLLM([])
        with pytest.raises(GuardrailError):
            await generate_proposal("Нужен бот", [], llm, model="strong")

    async def test_clean_first_attempt(self, portfolio) -> None:
        """Good output on attempt 1 → no retry."""
        llm = FakeLLM([GOOD_PROPOSAL])
        result = await generate_proposal(
            "Нужен Telegram-бот для записи", portfolio, llm, model="strong"
        )
        assert result.violations == []
        assert result.attempts == 1
        # §6.4: prompt must contain ONLY portfolio facts as the fact source.
        user_data = llm.calls[0]["messages"][1]["content"]
        assert "Бот записи для барбершопа" in user_data
        assert "Бот записи для барбершопа" not in llm.calls[0]["messages"][0]["content"]

    async def test_violation_triggers_one_retry(self, portfolio) -> None:
        """Bad first draft → retry with violation feedback (§6.4)."""
        bad = "Здравствуйте, увидел ваш проект. Сделаю быстро."
        llm = FakeLLM([bad, GOOD_PROPOSAL])
        result = await generate_proposal("Нужен бот", portfolio, llm, model="strong")
        assert result.attempts == 2
        assert result.violations == []
        retry_message = llm.calls[1]["messages"][-1]["content"]
        assert "Перепиши" in retry_message

    async def test_persistent_violations_returned_to_user(self, portfolio) -> None:
        """Two bad drafts → best one returned WITH warnings (not hidden)."""
        bad = "Выполню качественно и в срок."
        llm = FakeLLM([bad, bad])
        result = await generate_proposal("Нужен бот", portfolio, llm, model="strong")
        assert result.attempts == 2
        assert result.violations != []

    async def test_tone_variant_appended(self, portfolio) -> None:
        """Business tone variants (§7) modify the system prompt."""
        llm = FakeLLM([GOOD_PROPOSAL])
        await generate_proposal(
            "Нужен бот", portfolio, llm, model="strong", tone="formal"
        )
        assert "Тон" in llm.calls[0]["messages"][0]["content"]


class TestTemplateAndCases:
    def test_template_proposal_uses_portfolio_only(self, portfolio) -> None:
        """Basic-tier template references a real case and asks a question."""
        text = render_template_proposal("Нужен бот записи", portfolio)
        assert "Бот записи для барбершопа" in text
        assert text.rstrip().endswith("?")

    def test_template_without_portfolio_stays_neutral(self) -> None:
        """No portfolio → no fact claims at all."""
        text = render_template_proposal("Нужен бот", [])
        assert "опыт" not in text.casefold() or "по запросу" in text
        assert "лет" not in text.casefold()

    def test_select_relevant_cases_ranks_by_skills(self, portfolio) -> None:
        """§3.6: reorders existing cases, never invents new ones."""
        ranked = select_relevant_cases(
            portfolio, ["парсинг"], project_text="нужен парсер цен", k=2
        )
        assert ranked[0].title == "Парсер маркетплейсов"
        assert len(ranked) <= 2
        assert all(item in portfolio for item in ranked)

    async def test_portfolio_intro_generated_from_cases(self, portfolio) -> None:
        """§3.6: one adapted intro line grounded in real cases."""
        llm = FakeLLM(["Недавно делал бота записи для барбершопа — задача близкая."])
        intro = await generate_portfolio_intro(
            portfolio, "Нужен бот записи", llm, model="strong"
        )
        assert "барбершоп" in intro
        with pytest.raises(GuardrailError):
            await generate_portfolio_intro([], "т", llm, model="strong")
