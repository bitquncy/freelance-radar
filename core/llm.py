"""Thin async OpenRouter client — AGENTS.md §4.2, §6.1.

Two model tiers by cost/volume: a cheap model for per-listing extraction,
a strong model only for proposal generation. The client is intentionally
minimal and injectable so tests can pass a fake.
"""
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from services.logger_config import get_logger

logger = get_logger(__name__)


class LLMError(Exception):
    """Raised when the LLM gateway fails after retries."""


class _RetryableHTTPError(Exception):
    """Internal marker for retryable HTTP statuses (429/5xx)."""


class OpenRouterClient:
    """Async chat-completions client for OpenRouter-compatible APIs."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """Create a client.

        Args:
            api_key: OpenRouter (or compatible) API key.
            base_url: API base URL.
            timeout: Request timeout in seconds.
            client: Injectable httpx client (tests / custom transport).
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type(
            (_RetryableHTTPError, httpx.TransportError, httpx.TimeoutException)
        ),
        reraise=True,
    )
    async def _post_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        client = await self._get_client()
        response = await client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://github.com/bitquncy/freelance-radar",
                "X-Title": "FreelanceRadar",
            },
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableHTTPError(f"HTTP {response.status_code}")
        response.raise_for_status()
        data: Dict[str, Any] = response.json()
        return data

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 800,
        json_mode: bool = False,
    ) -> str:
        """Run a chat completion and return the assistant text.

        Args:
            messages: OpenAI-style message dicts.
            model: Model slug (e.g. ``openai/gpt-4o-mini``).
            temperature: Sampling temperature.
            max_tokens: Completion cap.
            json_mode: Ask the model for a JSON object response.

        Returns:
            Assistant message content.

        Raises:
            LLMError: On transport/API failure or empty completion.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = await self._post_chat(payload)
        except (
            _RetryableHTTPError,
            httpx.HTTPError,
        ) as exc:  # pragma: no cover - thin wrapper
            logger.error("llm.request_failed", model=model, error=str(exc))
            raise LLMError(str(exc)) from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("llm.bad_response", model=model, error=str(exc))
            raise LLMError("malformed completion response") from exc
        if not content:
            raise LLMError("empty completion")
        return str(content)


def get_default_llm_client() -> Optional[OpenRouterClient]:
    """Build a client from config, or ``None`` when no key is configured.

    Falls back to ``OPENAI_API_KEY``/``OPENAI_BASE_URL`` (the legacy bot's
    OpenRouter setup) when ``OPENROUTER_API_KEY`` is not set.
    """
    from config import get_config

    cfg = get_config()
    api_key = cfg.OPENROUTER_API_KEY or cfg.OPENAI_API_KEY
    if not api_key:
        return None
    base_url = cfg.OPENROUTER_BASE_URL
    if not cfg.OPENROUTER_API_KEY and cfg.OPENAI_BASE_URL:
        base_url = cfg.OPENAI_BASE_URL
    return OpenRouterClient(api_key=api_key, base_url=base_url)
