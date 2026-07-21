"""Response generator service v2 using OpenAI with profile and history context."""
import json
from typing import Optional, List

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
from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL
from db.models import JobVacancy, FreelancerProfile, Response

logger = get_logger(__name__)


class ResponseGenerator:
    """Service for generating responses to job vacancies using AI with personalization."""

    def __init__(self):
        # Initialize OpenAI client with optional custom base URL (for OpenRouter)
        client_kwargs = {"api_key": OPENAI_API_KEY, "timeout": 60.0}
        if OPENAI_BASE_URL:
            client_kwargs["base_url"] = OPENAI_BASE_URL
        self.client = AsyncOpenAI(**client_kwargs)
        self.model = OPENAI_MODEL
        self.rate_limiter = OpenAIRateLimiter(max_rpm=20, min_delay=3.0)
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
        
        # Log provider info
        provider = "OpenRouter" if OPENAI_BASE_URL and "openrouter" in OPENAI_BASE_URL.lower() else "OpenAI"
        logger.info("ai.provider_initialized", provider=provider, model=self.model)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((RateLimitError, APIError)),
        reraise=True,
    )
    async def generate_response(
        self,
        vacancy: JobVacancy,
        custom_prompt: Optional[str] = None,
        profile: Optional[FreelancerProfile] = None,
        recent_responses: Optional[List[Response]] = None
    ) -> Optional[str]:
        """
        Generate response text for a job vacancy.

        Args:
            vacancy: JobVacancy object to respond to
            custom_prompt: Optional custom response prompt from user settings
            profile: FreelancerProfile for personalization
            recent_responses: Recent responses for style consistency

        Returns:
            Generated response text or None if error
        """
        if not OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY is empty. Using fallback response template.")
            return self._build_fallback_response(vacancy, profile)

        if not self.circuit_breaker.can_execute():
            logger.warning("openai.circuit_open", kwork_id=vacancy.kwork_id)
            return self._build_fallback_response(vacancy, profile)

        try:
            await self.rate_limiter.acquire()
            system_prompt = self._build_system_prompt(custom_prompt, profile)
            user_prompt = self._build_user_prompt(vacancy, profile, recent_responses)

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=700
            )

            response_text = (response.choices[0].message.content or "").strip()
            if not response_text:
                logger.warning("OpenAI returned empty response. Using fallback template.")
                return self._build_fallback_response(vacancy, profile)

            self.circuit_breaker.record_success()

            logger.info("openai.response_generated", kwork_id=vacancy.kwork_id)
            return response_text

        except RateLimitError as e:
            self.circuit_breaker.record_failure()
            logger.error("openai.rate_limit_error", error=str(e))
            return self._build_fallback_response(vacancy, profile)
        except APIError as e:
            self.circuit_breaker.record_failure()
            logger.error("openai.api_error", error=str(e))
            return self._build_fallback_response(vacancy, profile)
        except (json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError, IndexError) as e:
            self.circuit_breaker.record_failure()
            logger.error("openai.unexpected_error", error=str(e))
            return self._build_fallback_response(vacancy, profile)

    def _build_system_prompt(
        self,
        custom_prompt: Optional[str] = None,
        profile: Optional[FreelancerProfile] = None
    ) -> str:
        """Build system prompt for response generation."""
        base_prompt = """Ты — профессиональный фрилансер, пишущий отклик на вакансию.

Твоя задача:
1. Написать краткий, профессиональный отклик (4-6 предложений)
2. Показать заинтересованность и компетентность
3. Упомянуть релевантный опыт и навыки
4. Предложить обсудить детали
5. Учитывать бюджет и сроки заказа

Стиль:
- Деловой, но дружелюбный
- Без излишней самопрезентации
- Конкретный и по делу
- На русском языке
- НЕ используй шаблонные фразы типа "Здравствуйте, меня заинтересовала ваша вакансия"
- Сразу переходи к сути, показывай экспертность"""

        parts = [base_prompt]

        if profile:
            profile_text = self._format_profile_for_prompt(profile)
            parts.append(f"\n\nИнформация о фрилансере:\n{profile_text}")

        if custom_prompt:
            parts.append(f"\n\nДополнительные требования от пользователя:\n{custom_prompt}")

        return "\n".join(parts)

    def _build_user_prompt(
        self,
        vacancy: JobVacancy,
        profile: Optional[FreelancerProfile] = None,
        recent_responses: Optional[List[Response]] = None
    ) -> str:
        """Build user prompt with vacancy details."""
        parts = [
            "Напиши отклик на эту вакансию:\n",
            f"Заголовок: {vacancy.title}",
            f"Описание: {vacancy.description}",
        ]

        if vacancy.budget:
            parts.append(f"Бюджет: {vacancy.budget}")
        if vacancy.deadline:
            parts.append(f"Срок: {vacancy.deadline}")
        if vacancy.category:
            parts.append(f"Категория: {vacancy.category}")
        if vacancy.skills:
            skills_list = vacancy.skills_list
            if skills_list:
                parts.append(f"Требуемые навыки: {', '.join(skills_list)}")

        # Include recent responses for style consistency
        if recent_responses:
            parts.append("\n\nПримеры твоих недавних откликов (держи похожий стиль):")
            for i, resp in enumerate(recent_responses[:3], 1):
                parts.append(f"\nОтклик {i}:\n{resp.response_text[:300]}")

        return "\n\n".join(parts)

    def _format_profile_for_prompt(self, profile: FreelancerProfile) -> str:
        """Format freelancer profile for prompt."""
        parts = []
        if profile.skills:
            skills_list = profile.skills_list
            parts.append(f"Навыки: {', '.join(skills_list)}")
        if profile.experience_years:
            parts.append(f"Опыт работы: {profile.experience_years} лет")
        if profile.strong_sides:
            parts.append(f"Сильные стороны: {profile.strong_sides}")
        if profile.hourly_rate:
            parts.append(f"Ставка: {profile.hourly_rate} руб/час")
        if profile.portfolio_url:
            parts.append(f"Портфолио: {profile.portfolio_url}")
        return "\n".join(parts) if parts else "Профиль не заполнен."

    def _build_fallback_response(
        self,
        vacancy: JobVacancy,
        profile: Optional[FreelancerProfile] = None
    ) -> str:
        """Build fallback response when OpenAI is unavailable."""
        parts = []

        # Personalized opening
        if profile and profile.strong_sides:
            parts.append(f"Привет! Я специализируюсь на {profile.strong_sides}.")
        else:
            parts.append(f"Готов взяться за задачу «{vacancy.title}».")

        parts.append("Изучил требования и могу оперативно приступить.")

        if vacancy.budget:
            parts.append(f"Бюджет {vacancy.budget} — обсуждаемо.")
        if vacancy.deadline:
            parts.append(f"Срок {vacancy.deadline} — укладываюсь.")

        parts.append(
            "Если удобно, отправьте детали по объему и ожидаемому результату, "
            "чтобы сразу согласовать финальный формат работы."
        )

        if profile and profile.portfolio_url:
            parts.append(f"Примеры работ: {profile.portfolio_url}")

        return " ".join(parts)
