"""Job analyzer service v2 using OpenAI with scoring and profile context."""
import asyncio
import json
import re
from typing import Optional, Dict, Any, List

from openai import AsyncOpenAI
from openai import RateLimitError, APIError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from services.logger_config import get_logger
from services.openai_rate_limiter import OpenAIRateLimiter
from services.circuit_breaker import CircuitBreaker
from services.ai_cache import get_ai_cache
from services.metrics import get_metrics
from constants import Priority, Complexity
from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL
from db.models import JobVacancy, FreelancerProfile

logger = get_logger(__name__)
_metrics = get_metrics()

# Default analysis result when everything fails
DEFAULT_ANALYSIS = {
    "suitable": False,
    "score": 0,
    "priority": "low",
    "reason": "Не удалось проанализировать вакансию",
    "extracted_budget": None,
    "extracted_deadline": None,
    "complexity": "unknown",
    "skills_required": [],
    "suggested_price": None,
    "risks": None,
    "match_percentage": 0,
}

# Required fields for analysis result
REQUIRED_FIELDS = [
    "suitable", "score", "priority", "reason",
    "extracted_budget", "extracted_deadline", "complexity",
    "skills_required", "suggested_price", "risks", "match_percentage"
]


class JobAnalyzer:
    """Service for analyzing job vacancies using AI with scoring."""

    def __init__(self):
        # Initialize OpenAI client with optional custom base URL (for OpenRouter)
        client_kwargs = {"api_key": OPENAI_API_KEY, "timeout": 60.0}
        if OPENAI_BASE_URL:
            client_kwargs["base_url"] = OPENAI_BASE_URL
        self.client = AsyncOpenAI(**client_kwargs)
        self.model = OPENAI_MODEL
        self.rate_limiter = OpenAIRateLimiter(max_rpm=20, min_delay=3.0)
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
        self.ai_cache = get_ai_cache()
        self._semaphore = asyncio.Semaphore(5)
        
        # Log provider info
        provider = "OpenRouter" if OPENAI_BASE_URL and "openrouter" in OPENAI_BASE_URL.lower() else "OpenAI"
        logger.info("ai.provider_initialized", provider=provider, model=self.model)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((RateLimitError, APIError)),
        reraise=True,
    )
    async def analyze_job(
        self,
        vacancy: JobVacancy,
        custom_prompt: Optional[str] = None,
        profile: Optional[FreelancerProfile] = None
    ) -> Dict[str, Any]:
        """
        Analyze job vacancy using OpenAI.

        Returns:
            Dictionary with analysis results.
        """
        if not OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY is empty. Using fallback analysis.")
            return self._fallback_analysis(vacancy, profile)

        if not self.circuit_breaker.can_execute():
            logger.warning("openai.circuit_open", kwork_id=vacancy.kwork_id)
            return self._fallback_analysis(vacancy, profile)

        # Check cache first
        vacancy_data = {"title": vacancy.title, "description": vacancy.description, "budget": vacancy.budget}
        cached = await self.ai_cache.get(vacancy.kwork_id, vacancy_data)
        if cached is not None:
            logger.info("ai_cache.hit", kwork_id=vacancy.kwork_id)
            return cached

        try:
            await self.rate_limiter.acquire()
            system_prompt = self._build_system_prompt(custom_prompt, profile)
            user_prompt = self._build_user_prompt(vacancy, profile)

            logger.info(
                "openai.request_started",
                kwork_id=vacancy.kwork_id,
                model=self.model,
                prompt_length=len(user_prompt),
            )

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
                max_tokens=800,
            )

            raw_content = response.choices[0].message.content or ""

            self.circuit_breaker.record_success()

            # Track token usage
            if response.usage:
                _metrics.counter("openai_tokens_prompt_total").inc(response.usage.prompt_tokens)
                _metrics.counter("openai_tokens_completion_total").inc(response.usage.completion_tokens)
                _metrics.counter("openai_tokens_total").inc(response.usage.total_tokens)

            logger.info(
                "openai.response_received",
                kwork_id=vacancy.kwork_id,
                raw_length=len(raw_content),
                raw_preview=raw_content[:200],
                tokens_used=response.usage.total_tokens if response.usage else 0,
            )

            # Parse JSON with robust fallback
            result = self._parse_json_response(raw_content)

            # Validate and fix result
            result = self._validate_result(result, vacancy, profile)

            # Cache successful result
            vacancy_data = {"title": vacancy.title, "description": vacancy.description, "budget": vacancy.budget}
            await self.ai_cache.set(vacancy.kwork_id, vacancy_data, result)

            logger.info(
                "openai.analysis_completed",
                kwork_id=vacancy.kwork_id,
                score=result.get("score", 0),
                priority=result.get("priority", "unknown"),
                match=result.get("match_percentage", 0),
                suitable=result.get("suitable", False),
            )

            return result

        except RateLimitError as e:
            self.circuit_breaker.record_failure()
            logger.error("openai.rate_limit_error", error=str(e))
            return self._fallback_analysis(vacancy, profile)
        except APIError as e:
            self.circuit_breaker.record_failure()
            logger.error("openai.api_error", error=str(e))
            return self._fallback_analysis(vacancy, profile)
        except (json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError, IndexError) as e:
            self.circuit_breaker.record_failure()
            logger.error("openai.unexpected_error", error=str(e))
            return self._fallback_analysis(vacancy, profile)

    async def analyze_jobs(
        self,
        vacancies: List[JobVacancy],
        custom_prompt: Optional[str] = None,
        profile: Optional[FreelancerProfile] = None,
        max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        """Analyze multiple vacancies in parallel with concurrency limit.

        Args:
            vacancies: List of vacancies to analyze.
            custom_prompt: Optional custom analysis prompt.
            profile: Optional freelancer profile.
            max_concurrent: Max parallel OpenAI requests.

        Returns:
            List of analysis results (same order as input).
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _analyze_one(vacancy: JobVacancy) -> Dict[str, Any]:
            async with semaphore:
                return await self.analyze_job(vacancy, custom_prompt, profile)

        logger.info(
            "openai.batch_analysis_started",
            count=len(vacancies),
            max_concurrent=max_concurrent,
        )

        results = await asyncio.gather(
            *[_analyze_one(v) for v in vacancies],
            return_exceptions=True,
        )

        # Convert exceptions to fallback results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "openai.batch_item_failed",
                    kwork_id=vacancies[i].kwork_id,
                    error=str(result),
                )
                final_results.append(self._fallback_analysis(vacancies[i], profile))
            else:
                final_results.append(result)

        logger.info(
            "openai.batch_analysis_completed",
            count=len(vacancies),
            successful=sum(1 for r in final_results if r.get("score", 0) > 0),
        )
        return final_results

    def _parse_json_response(self, raw: str) -> Dict[str, Any]:
        """Parse JSON response with multiple fallback strategies."""
        # Strategy 1: direct JSON parse
        try:
            result = json.loads(raw)
            logger.debug("json_parse.direct_success")
            return result
        except json.JSONDecodeError:
            pass

        # Strategy 2: strip markdown code blocks
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)
            logger.debug("json_parse.markdown_stripped_success")
            return result
        except json.JSONDecodeError:
            pass

        # Strategy 3: extract JSON object from text
        match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
                logger.debug("json_parse.regex_extract_success")
                return result
            except json.JSONDecodeError:
                pass

        # Strategy 4: extract JSON object with nested braces
        depth = 0
        start = -1
        for i, c in enumerate(cleaned):
            if c == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        result = json.loads(cleaned[start:i+1])
                        logger.debug("json_parse.nested_extract_success")
                        return result
                    except json.JSONDecodeError:
                        start = -1

        logger.warning(
            "json_parse.all_strategies_failed",
            raw_preview=raw[:500],
        )
        return {}

    def _validate_result(
        self,
        result: Dict[str, Any],
        vacancy: JobVacancy,
        profile: Optional[FreelancerProfile]
    ) -> Dict[str, Any]:
        """Validate and fix result, ensuring all required fields exist with correct types."""
        if not result:
            return self._fallback_analysis(vacancy, profile)

        # Ensure all required fields exist
        for field in REQUIRED_FIELDS:
            if field not in result:
                result[field] = DEFAULT_ANALYSIS.get(field)

        # Fix types
        result["suitable"] = bool(result.get("suitable", False))
        result["score"] = self._clamp_int(result.get("score", 0), 0, 100)
        result["match_percentage"] = self._clamp_int(result.get("match_percentage", 0), 0, 100)
        result["priority"] = result.get("priority", Priority.LOW)
        if result.get("priority") not in (Priority.LOW, Priority.MEDIUM, Priority.HIGH):
            result["priority"] = Priority.LOW
        result["complexity"] = result.get("complexity", Complexity.UNKNOWN)
        if result.get("complexity") not in (Complexity.LOW, Complexity.MEDIUM, Complexity.HIGH):
            result["complexity"] = Complexity.UNKNOWN
        result["reason"] = str(result.get("reason", "")) or "Нет данных"
        result["skills_required"] = result.get("skills_required", [])
        if not isinstance(result["skills_required"], list):
            result["skills_required"] = []

        # If score is 0 but we have vacancy data, apply fallback scoring
        if result["score"] == 0:
            logger.warning(
                "openai.score_zero_fallback",
                kwork_id=vacancy.kwork_id,
                reason="OpenAI returned score=0, applying fallback scoring",
            )
            result = self._fallback_analysis(vacancy, profile)
            return result

        # If match_percentage is 0, recalculate based on vacancy data
        if result["match_percentage"] == 0 and profile:
            result["match_percentage"] = self._calculate_match_from_data(vacancy, profile)
            logger.info(
                "openai.match_recalculated",
                kwork_id=vacancy.kwork_id,
                match=result["match_percentage"],
            )

        # Ensure suitable is consistent with score
        if result["score"] >= 50:
            result["suitable"] = True

        return result

    def _fallback_analysis(
        self,
        vacancy: JobVacancy,
        profile: Optional[FreelancerProfile]
    ) -> Dict[str, Any]:
        """Fallback analysis when AI fails. Returns reasonable scores."""
        score = 0
        match = 0
        priority = "low"

        # Base score for having valid vacancy data
        if vacancy.title and vacancy.description:
            score += 10

        # Score based on budget
        if vacancy.budget_min and vacancy.budget_min > 0:
            if vacancy.budget_min >= 50000:
                score += 30
            elif vacancy.budget_min >= 20000:
                score += 20
            elif vacancy.budget_min >= 5000:
                score += 10
            else:
                score += 5
        elif vacancy.budget:
            numbers = re.findall(r'\d+', vacancy.budget)
            if numbers:
                budget_val = int(numbers[0])
                if budget_val >= 50000:
                    score += 30
                elif budget_val >= 20000:
                    score += 20
                elif budget_val >= 5000:
                    score += 10
                else:
                    score += 5
        else:
            score += 5

        # Score based on deadline
        if vacancy.deadline_days:
            if vacancy.deadline_days >= 14:
                score += 15
            elif vacancy.deadline_days >= 7:
                score += 10
            elif vacancy.deadline_days >= 3:
                score += 5
        elif vacancy.deadline:
            score += 5

        # Score based on customer rating
        if vacancy.customer_rating and vacancy.customer_rating >= 4.0:
            score += 10
        elif vacancy.customer_rating and vacancy.customer_rating >= 3.0:
            score += 5

        # Score based on orders count
        if vacancy.customer_orders and vacancy.customer_orders >= 10:
            score += 10
        elif vacancy.customer_orders and vacancy.customer_orders >= 5:
            score += 5

        # Score based on skills match
        if profile and profile.skills:
            profile_skills = set(s.lower() for s in profile.skills_list)
            vacancy_skills = set(s.lower() for s in (vacancy.skills_list if vacancy.skills else []))
            if profile_skills and vacancy_skills:
                common = profile_skills & vacancy_skills
                if common:
                    score += min(30, len(common) * 10)
                elif vacancy_skills:
                    score += 5
        elif vacancy.skills:
            score += 5

        # Score for proposals count (fewer = better)
        if vacancy.proposals_count is not None:
            if vacancy.proposals_count < 5:
                score += 10
            elif vacancy.proposals_count < 15:
                score += 5

        # Priority based on score
        if score >= 70:
            priority = Priority.HIGH
        elif score >= 40:
            priority = Priority.MEDIUM
        else:
            priority = Priority.LOW

        # Match percentage
        if profile and profile.skills:
            profile_skills = set(s.lower() for s in profile.skills_list)
            vacancy_skills = set(s.lower() for s in (vacancy.skills_list if vacancy.skills else []))
            if profile_skills and vacancy_skills:
                common = profile_skills & vacancy_skills
                match = int((len(common) / len(profile_skills)) * 100) if profile_skills else 0
                match = min(100, match)
        elif vacancy.skills:
            match = 20

        # Cap score at 100
        score = min(100, score)

        # Ensure minimum score for valid vacancies
        if score < 15 and vacancy.title:
            score = 15

        return {
            "suitable": score >= 50,
            "score": score,
            "priority": priority,
            "reason": "Базовая оценка (AI недоступен): бюджет, сроки, навыки",
            "extracted_budget": vacancy.budget,
            "extracted_deadline": vacancy.deadline,
            "complexity": "unknown",
            "skills_required": vacancy.skills_list if vacancy.skills else [],
            "suggested_price": vacancy.budget_min or vacancy.budget_max,
            "risks": None,
            "match_percentage": match,
        }

    def _calculate_match_from_data(
        self,
        vacancy: JobVacancy,
        profile: FreelancerProfile
    ) -> int:
        """Calculate match percentage from vacancy and profile data without AI."""
        match = 0

        if not profile.skills:
            return 0

        profile_skills = set(s.lower() for s in profile.skills_list)
        vacancy_skills = set(s.lower() for s in (vacancy.skills_list if vacancy.skills else []))

        if profile_skills and vacancy_skills:
            common = profile_skills & vacancy_skills
            match = int((len(common) / len(profile_skills)) * 100)
            match = min(100, match)

        # Budget match
        if profile.min_budget and vacancy.budget_min:
            if vacancy.budget_min >= profile.min_budget:
                match += 20

        if profile.max_budget and vacancy.budget_max:
            if vacancy.budget_max <= profile.max_budget:
                match += 20

        match = min(100, match)
        return match

    @staticmethod
    def _clamp_int(value, min_val: int, max_val: int) -> int:
        """Clamp value to range."""
        try:
            return max(min_val, min(max_val, int(value)))
        except (TypeError, ValueError):
            return min_val

    def _build_system_prompt(
        self,
        custom_prompt: Optional[str] = None,
        profile: Optional[FreelancerProfile] = None
    ) -> str:
        """Build system prompt for job analysis."""
        parts = [
            "Ты — профессиональный помощник фрилансера. Анализируй вакансии и возвращай результат СТРОГО в формате JSON.",
            "",
            "КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА:",
            "1. Отвечай ТОЛЬКО валидным JSON. Никакого текста до или после JSON.",
            "2. Не используй markdown-разметку, код блоки (```) или что-либо кроме JSON.",
            "3. Все поля ОБЯЗАТЕЛЬНЫ. Не пропускай ни одного поля.",
            "4. Оценка score ОБЯЗАНА быть числом от 0 до 100. НЕ ставь 0 без веской причины.",
            "5. match_percentage ОБЯЗАН быть числом от 0 до 100.",
            "6. priority ОБЯЗАН быть одним из: low, medium, high.",
            "7. complexity ОБЯЗАН быть одним из: low, medium, high.",
            "8. skills_required — массив строк (навыки). Если навыки неизвестны, верни пустой массив [].",
            "9. suitable — true если score >= 50, иначе false.",
            "10. risks — строка с описанием рисков. Если рисков нет, верни null.",
            "",
            "КРИТЕРИИ ОЦЕНКИ (score):",
            "- Бюджет 50000+ ₽: +30 баллов",
            "- Бюджет 20000-49999 ₽: +20 баллов",
            "- Бюджет 5000-19999 ₽: +10 баллов",
            "- Срок 14+ дней: +15 баллов",
            "- Срок 7-13 дней: +10 баллов",
            "- Срок 3-6 дней: +5 баллов",
            "- Рейтинг заказчика >= 4.0: +10 баллов",
            "- Заказов 10+: +10 баллов",
            "- Совпадение навыков: +30 баллов (полное), +20 (частичное), +10 (небольшое)",
            "- Чистое описание, прозрачные условия: +10 баллов",
            "- Вague описание, непонятные требования: -10 баллов",
            "- Подозрительный бюджет (слишком низкий/высокий): -20 баллов",
            "",
            "ОЦЕНКА ПРИОРИТЕТА:",
            "- high: score >= 70",
            "- medium: score >= 40",
            "- low: score < 40",
            "",
            "ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО):",
            '{"suitable": true, "score": 75, "priority": "high", "reason": "описание", "extracted_budget": "25000 ₽", "extracted_deadline": "5 дней", "complexity": "medium", "skills_required": ["Python", "Django"], "suggested_price": 25000, "risks": "описание рисков", "match_percentage": 80}',
            "",
            "ВАЖНО: score должен быть реалистичным. Если вакансия хорошая — ставь 50-100. Если средняя — 30-50. Если плохая — 10-30. Минимальный score для любой валидной вакансии с заголовком и описанием — 10. Ставь 0 ТОЛЬКО если вакансия полностью пустая или нерелевантная.",
        ]

        if profile:
            profile_info = self._format_profile_for_prompt(profile)
            parts.append(f"\nПрофиль фрилансера:\n{profile_info}")
            parts.append("\nОцени match_percentage на основе совпадения навыков фрилансера с требованиями вакансии. Если навыки фрилансера совпадают с 50%+ требований — ставь 60-100%. Если 20-50% — ставь 30-60%. Если <20% — ставь 0-30%.")
        else:
            parts.append("\nПрофиль фрилансера не заполнен. Оцени по бюджету, срокам и общему качеству вакансии. match_percentage ставь на основе бюджета (30-100) и общего качества.")

        if custom_prompt:
            parts.append(f"\nДополнительные критерии от пользователя:\n{custom_prompt}")

        return "\n".join(parts)

    def _build_user_prompt(
        self,
        vacancy: JobVacancy,
        profile: Optional[FreelancerProfile] = None
    ) -> str:
        """Build user prompt with vacancy details."""
        parts = [
            "Проанализируй эту вакансию и верни JSON:",
            "",
            f"Заголовок: {vacancy.title}",
            f"Описание: {vacancy.description[:500]}",
        ]

        if vacancy.budget:
            parts.append(f"Бюджет: {vacancy.budget}")
        if vacancy.budget_min or vacancy.budget_max:
            parts.append(f"Бюджет (числа): {vacancy.budget_min} - {vacancy.budget_max}")
        if vacancy.deadline:
            parts.append(f"Срок: {vacancy.deadline}")
        if vacancy.deadline_days:
            parts.append(f"Срок (дней): {vacancy.deadline_days}")
        if vacancy.category:
            parts.append(f"Категория: {vacancy.category}")
        if vacancy.subcategory:
            parts.append(f"Подкатегория: {vacancy.subcategory}")
        if vacancy.skills:
            skills_list = vacancy.skills_list
            parts.append(f"Навыки (из источника): {', '.join(skills_list)}")
        if vacancy.proposals_count:
            parts.append(f"Количество предложений: {vacancy.proposals_count}")
        if vacancy.customer_rating:
            parts.append(f"Рейтинг заказчика: {vacancy.customer_rating}")
        if vacancy.customer_orders:
            parts.append(f"Заказов у клиента: {vacancy.customer_orders}")

        parts.append(f"Источник: {vacancy.source}")

        return "\n\n".join(parts)

    def _format_profile_for_prompt(self, profile: FreelancerProfile) -> str:
        """Format freelancer profile for AI prompt."""
        parts = []
        if profile.skills:
            skills_list = profile.skills_list
            parts.append(f"Навыки: {', '.join(skills_list)}")
        if profile.experience_years:
            parts.append(f"Опыт работы: {profile.experience_years} лет")
        if profile.preferred_categories:
            categories_list = profile.preferred_categories_list
            parts.append(f"Предпочтительные категории: {', '.join(categories_list)}")
        if profile.hourly_rate:
            parts.append(f"Ставка: {profile.hourly_rate} руб/час")
        if profile.strong_sides:
            parts.append(f"Сильные стороны: {profile.strong_sides}")
        if profile.bio:
            parts.append(f"О себе: {profile.bio}")
        return "\n".join(parts) if parts else "Профиль не заполнен."

    def _error_response(self, error_message: str) -> Dict[str, Any]:
        """Return error response in expected format."""
        return {
            "suitable": False,
            "score": 0,
            "priority": "low",
            "reason": f"Ошибка анализа: {error_message}",
            "extracted_budget": None,
            "extracted_deadline": None,
            "complexity": "unknown",
            "skills_required": [],
            "suggested_price": None,
            "risks": None,
            "match_percentage": 0,
        }

    async def extract_price_range(self, text: str) -> Optional[Dict[str, int]]:
        """Extract price range from text."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Извлеки диапазон цен из текста. Ответь в JSON: {\"min\": число, \"max\": число} или {\"min\": null, \"max\": null}"
                    },
                    {"role": "user", "content": text}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            if result.get("min") is not None or result.get("max") is not None:
                return {
                    "min": result.get("min"),
                    "max": result.get("max")
                }

            return None

        except (RateLimitError, APIError, json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            logger.error("openai.price_range_error", error=str(e))
            return None
