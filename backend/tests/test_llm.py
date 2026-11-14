import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIStatusError
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.services.llm import LLMError, OpenRouterService


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str


def completion(content='{"summary":"Fix denominator"}', reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=reason)])


def service(**overrides):
    settings = Settings(_env_file=None, openrouter_api_key="test-only", **overrides)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())), close=AsyncMock())
    return OpenRouterService(settings, client), client.chat.completions.create


def test_valid_structured_response():
    llm, create = service()
    create.return_value = completion()
    result = asyncio.run(llm.generate("Investigate", Answer))
    assert result.summary == "Fix denominator"
    assert create.call_args.kwargs["model"] == "openrouter/free"
    assert create.call_args.kwargs["response_format"]["type"] == "json_schema"
    assert "tools" not in create.call_args.kwargs
    asyncio.run(llm.close())
    llm.client.close.assert_awaited_once()


@pytest.mark.parametrize("bad", ['not json', '{"summary":4}', '{"summary":"ok","extra":1}', None])
def test_invalid_output_retried(bad):
    llm, create = service()
    create.side_effect = [completion(bad), completion()]
    with patch("app.services.llm.asyncio.sleep", new_callable=AsyncMock):
        assert asyncio.run(llm.generate("Investigate", Answer)).summary
    assert create.await_count == 2


def test_retry_limit_and_truncated_output():
    llm, create = service(llm_max_attempts=2)
    create.return_value = completion(reason="length")
    with patch("app.services.llm.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError, match="configured attempts"):
            asyncio.run(llm.generate("Investigate", Answer))
    assert create.await_count == 2


@pytest.mark.parametrize("status,retries", [(401, 1), (400, 1), (429, 3), (503, 3)])
def test_http_retry_policy(status, retries):
    llm, create = service()
    response = httpx.Response(status, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    create.side_effect = APIStatusError("sensitive provider error", response=response, body=None)
    with patch("app.services.llm.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError) as error:
            asyncio.run(llm.generate("Investigate", Answer))
    assert "sensitive" not in str(error.value)
    assert create.await_count == retries


def test_prompt_mode_still_validates():
    llm, create = service(openrouter_structured_outputs=False)
    create.return_value = completion()
    assert asyncio.run(llm.generate("Investigate", Answer)).summary
    assert "response_format" not in create.call_args.kwargs


def test_timeout_retried():
    llm, create = service(llm_max_attempts=2)
    create.side_effect = [TimeoutError(), completion()]
    with patch("app.services.llm.asyncio.sleep", new_callable=AsyncMock):
        assert asyncio.run(llm.generate("Investigate", Answer)).summary
    assert create.await_count == 2


def test_no_credentials_or_other_provider():
    with pytest.raises(LLMError, match="Configure"):
        OpenRouterService(Settings(_env_file=None, openrouter_api_key=""))
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openrouter_base_url="https://api.openai.com/v1")
