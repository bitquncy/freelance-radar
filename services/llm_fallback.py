"""Self-hosted LLM fallback using Ollama API."""
import json
from typing import Optional, Dict, Any

import httpx

from services.logger_config import get_logger
from config import OPENAI_API_KEY
from db.models import JobVacancy, FreelancerProfile

logger = get_logger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


class LLMFallback:
    """Fallback LLM client using Ollama for when OpenAI is unavailable."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = DEFAULT_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(timeout=60.0)

    async def is_available(self) -> bool:
        """Check if Ollama is running."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except (ConnectionError, OSError, ValueError, TypeError):
            return False

    async def analyze_job(
        self,
        vacancy: JobVacancy,
        profile: Optional[FreelancerProfile] = None
    ) -> Dict[str, Any]:
        """Analyze job using local LLM."""
        system_prompt = """Ты — профессиональный помощник фрилансера. Анализируй вакансии и отвечай СТРОГО в JSON формате:
{
    "suitable": true/false,
    "score": число от 0 до 100,
    "priority": "low" | "medium" | "high",
    "reason": "краткое объяснение",
    "extracted_budget": "бюджет или null",
    "extracted_deadline": "срок или null",
    "complexity": "low/medium/high",
    "skills_required": ["навык1", "навык2"],
    "suggested_price": число или null,
    "risks": "описание рисков или null",
    "match_percentage": число от 0 до 100
}"""

        user_prompt = f"""Заголовок: {vacancy.title}
Описание: {vacancy.description}
Бюджет: {vacancy.budget or 'не указан'}
Срок: {vacancy.deadline or 'не указан'}
Категория: {vacancy.category or 'не указана'}
"""
        if profile and profile.skills:
            skills_list = profile.skills_list
            user_prompt += f"\nНавыки фрилансера: {', '.join(skills_list)}"

        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "format": "json",
                }
            )
            response.raise_for_status()
            data = response.json()

            # Parse JSON from response
            content = data.get("response", "")
            result = json.loads(content)

            logger.info("llm.analyzed", kwork_id=vacancy.kwork_id, score=result.get("score", 0))
            return result

        except (ConnectionError, OSError, json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("llm.error", error=str(e))
            return self._error_response(str(e))

    async def generate_response(
        self,
        vacancy: JobVacancy,
        profile: Optional[FreelancerProfile] = None
    ) -> Optional[str]:
        """Generate response using local LLM."""
        system_prompt = """Ты — профессиональный фрилансер, пишущий отклик на вакансию.
Напиши краткий, профессиональный отклик (4-6 предложений).
Стиль: деловой, но дружелюбный, без шаблонных фраз.
На русском языке."""

        user_prompt = f"""Напиши отклик на вакансию:
Заголовок: {vacancy.title}
Описание: {vacancy.description}
Бюджет: {vacancy.budget or 'не указан'}
Срок: {vacancy.deadline or 'не указан'}
"""
        if profile:
            if profile.skills:
                skills_list = profile.skills_list
                user_prompt += f"\nМои навыки: {', '.join(skills_list)}"
            if profile.strong_sides:
                user_prompt += f"\nСильные стороны: {profile.strong_sides}"

        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()

        except (ConnectionError, OSError, json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("llm.response_generation_error", error=str(e))
            return None

    def _error_response(self, error_message: str) -> Dict[str, Any]:
        """Return error response."""
        return {
            "suitable": False,
            "score": 0,
            "priority": "low",
            "reason": f"Local LLM error: {error_message}",
            "extracted_budget": None,
            "extracted_deadline": None,
            "complexity": "unknown",
            "skills_required": [],
            "suggested_price": None,
            "risks": None,
            "match_percentage": 0,
        }

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


async def get_llm_client():
    """Get appropriate LLM client (OpenAI primary, Ollama fallback)."""
    if OPENAI_API_KEY:
        return None  # Use OpenAI (JobAnalyzer/ResponseGenerator)

    fallback = LLMFallback()
    if await fallback.is_available():
        logger.info("Using Ollama as LLM fallback")
        return fallback

    logger.warning("No LLM available (OpenAI key missing, Ollama not running)")
    return None
