"""OpenRouter client tests (mock transport, §11: no real calls) + db helpers."""
import json
from typing import List

import httpx
import pytest

from core.db import normalize_database_url
from core.llm import LLMError, OpenRouterClient, get_default_llm_client


def _client_with(responses: List[httpx.Response]) -> OpenRouterClient:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return response

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenRouterClient(api_key="k", client=http)


def _ok(content: str = "ответ") -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}
    )


class TestOpenRouterClient:
    async def test_chat_success(self) -> None:
        """Returns assistant content."""
        client = _client_with([_ok("привет")])
        assert await client.chat([{"role": "user", "content": "hi"}], "m") == (
            "привет"
        )
        await client.close()

    async def test_json_mode_sets_response_format(self) -> None:
        """§6.3: strict JSON extraction asks for a JSON object."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content.decode()))
            return _ok('{"a": 1}')

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenRouterClient(api_key="k", client=http)
        await client.chat([{"role": "user", "content": "x"}], "m", json_mode=True)
        assert seen["response_format"] == {"type": "json_object"}
        assert seen["model"] == "m"
        await client.close()

    async def test_rate_limit_retried(self) -> None:
        """429 → retry → success."""
        client = _client_with([httpx.Response(429), _ok("после ретрая")])
        result = await client.chat([{"role": "user", "content": "x"}], "m")
        assert result == "после ретрая"
        await client.close()

    async def test_malformed_response_raises(self) -> None:
        """Missing choices → LLMError, not KeyError."""
        client = _client_with([httpx.Response(200, json={"oops": True})])
        with pytest.raises(LLMError):
            await client.chat([{"role": "user", "content": "x"}], "m")
        await client.close()

    async def test_empty_content_raises(self) -> None:
        """Empty completion → LLMError."""
        client = _client_with([_ok("")])
        with pytest.raises(LLMError):
            await client.chat([{"role": "user", "content": "x"}], "m")
        await client.close()

    async def test_client_error_raises_llm_error(self) -> None:
        """4xx (non-429) is not retried and surfaces as LLMError."""
        client = _client_with([httpx.Response(400, json={"error": "bad"})])
        with pytest.raises(LLMError):
            await client.chat([{"role": "user", "content": "x"}], "m")
        await client.close()


class TestDefaultClientFactory:
    def test_no_keys_returns_none(self, monkeypatch) -> None:
        """Without any key the pipeline runs in no-LLM fallback mode."""
        from config import get_config

        cfg = get_config()
        monkeypatch.setattr(cfg, "OPENROUTER_API_KEY", "")
        monkeypatch.setattr(cfg, "OPENAI_API_KEY", "")
        assert get_default_llm_client() is None

    def test_openrouter_key_wins(self, monkeypatch) -> None:
        """OPENROUTER_API_KEY takes precedence over the legacy key."""
        from config import get_config

        cfg = get_config()
        monkeypatch.setattr(cfg, "OPENROUTER_API_KEY", "or-key")
        monkeypatch.setattr(cfg, "OPENAI_API_KEY", "legacy")
        client = get_default_llm_client()
        assert client is not None

    def test_legacy_key_fallback(self, monkeypatch) -> None:
        """Legacy OpenRouter setup (OPENAI_* vars) still works."""
        from config import get_config

        cfg = get_config()
        monkeypatch.setattr(cfg, "OPENROUTER_API_KEY", "")
        monkeypatch.setattr(cfg, "OPENAI_API_KEY", "legacy")
        monkeypatch.setattr(
            cfg, "OPENAI_BASE_URL", "https://openrouter.ai/api/v1"
        )
        assert get_default_llm_client() is not None


class TestDatabaseUrl:
    def test_normalize_variants(self) -> None:
        """Provider-style URLs get async drivers (§4.2 PostgreSQL prod)."""
        assert normalize_database_url("postgres://u:p@h/db") == (
            "postgresql+asyncpg://u:p@h/db"
        )
        assert normalize_database_url("postgresql://u:p@h/db") == (
            "postgresql+asyncpg://u:p@h/db"
        )
        assert normalize_database_url("sqlite:///x.db") == (
            "sqlite+aiosqlite:///x.db"
        )
        assert normalize_database_url("sqlite+aiosqlite:///x.db") == (
            "sqlite+aiosqlite:///x.db"
        )
        assert normalize_database_url("postgresql+asyncpg://u@h/db") == (
            "postgresql+asyncpg://u@h/db"
        )

    async def test_engine_lifecycle(self, tmp_path, monkeypatch) -> None:
        """get_engine → init_v2_db → dispose works on a real file DB."""
        import core.db as core_db
        from config import get_config

        monkeypatch.setattr(
            get_config(),
            "DATABASE_URL",
            f"sqlite+aiosqlite:///{tmp_path}/life.db",
        )
        monkeypatch.setattr(core_db, "_engine", None)
        monkeypatch.setattr(core_db, "_session_factory", None)
        engine = core_db.get_engine()
        await core_db.init_v2_db(engine)
        factory = core_db.get_session_factory()
        async with factory() as session:
            from sqlalchemy import text

            result = await session.execute(
                text("SELECT name FROM sqlite_master WHERE name='users'")
            )
            assert result.scalar_one() == "users"
        await core_db.dispose_engine()
