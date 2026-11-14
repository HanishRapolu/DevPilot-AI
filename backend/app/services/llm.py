import asyncio
import json
from typing import TypeVar

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Sanitized error safe to surface without credentials or model response content."""


class OpenRouterService:
    """One bounded retry loop; no tool calling and no automatic paid fallback."""

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        if not settings.openrouter_api_key.get_secret_value():
            raise LLMError("Configure OPENROUTER_API_KEY in backend/.env")
        self.settings = settings
        self.client = client or AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=settings.llm_timeout_seconds, max_retries=0,
        )

    async def close(self) -> None:
        await self.client.close()

    async def generate(self, prompt: str, schema: type[T]) -> T:
        if not prompt.strip() or len(prompt) > 40000:
            raise ValueError("Prompt must contain 1–40000 characters")
        messages = [
            {"role": "system", "content": "Return only a JSON object matching this schema: " + json.dumps(schema.model_json_schema())},
            {"role": "user", "content": prompt},
        ]
        options = {}
        if self.settings.openrouter_structured_outputs:
            options = {
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "strict": True, "schema": schema.model_json_schema()}},
                "extra_body": {"provider": {"require_parameters": True}},
            }
        for attempt in range(self.settings.llm_max_attempts):
            try:
                # Outer timeout bounds the entire attempt in addition to SDK network timeouts.
                async with asyncio.timeout(self.settings.llm_timeout_seconds):
                    response = await self.client.chat.completions.create(
                        model=self.settings.openrouter_model, messages=messages,
                        max_tokens=2048, **options,
                    )
                if not response.choices or response.choices[0].finish_reason != "stop":
                    raise ValueError("Missing or incomplete output")
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Empty output")
                return schema.model_validate_json(content, strict=True)
            except APIStatusError as exc:
                if exc.status_code not in (408, 429) and exc.status_code < 500:
                    raise LLMError(f"OpenRouter rejected the request (HTTP {exc.status_code}). Check model capabilities and configuration.") from None
            except (APIConnectionError, TimeoutError, ValidationError, ValueError):
                pass
            if attempt + 1 < self.settings.llm_max_attempts:
                await asyncio.sleep(min(2 ** attempt, 4))
        raise LLMError("OpenRouter did not return a valid result within the configured attempts.")
