import asyncio
import json
import socket
import logging
from typing import TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Sanitized error safe to surface without credentials or model response content."""


class OutputError(ValueError):
    """Only application-generated diagnostics, never raw model content."""


def validate_response(response, schema):
    if not response.choices:
        raise OutputError("missing_choices: provider returned no completion choices.")
    choice = response.choices[0]
    reason = choice.finish_reason
    if reason == "length":
        raise OutputError("output_truncated: finish_reason=length. Increase LLM_MAX_OUTPUT_TOKENS and retry.")
    if reason == "content_filter" or getattr(choice.message, "refusal", None):
        raise OutputError("response_refused: provider filtered or refused the response. Review the request.")
    if reason != "stop":
        raise OutputError("unexpected_finish_reason: provider did not finish a normal text response.")
    content = choice.message.content
    if not content or not content.strip():
        raise OutputError("empty_content: response finished without usable text.")
    try:
        return schema.model_validate_json(content, strict=True)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        if any(e['type'] == 'json_invalid' for e in errors):
            raise OutputError("invalid_json: response was not valid JSON. Return JSON only, without Markdown fences or unescaped newlines.") from None
        # Only schema-owned field names are allowed in diagnostic output.
        details = sorted({str(e['loc'][0]) + ':' + e['type']
                          for e in errors if e['loc'] and e['loc'][0] in schema.model_fields})
        if any(e['type'] == 'extra_forbidden' for e in errors):
            details.append('unexpected_fields')
        raise OutputError("schema_mismatch: " + (', '.join(details) or 'invalid field structure') + ". Return the required fields and types.") from None


def connection_detail(exc: Exception) -> str:
    cause = exc
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, socket.gaierror):
            return "DNS resolution failed for openrouter.ai. Check internet access and DNS settings."
        cause = cause.__cause__ or cause.__context__
    return "Cannot connect to OpenRouter. Check internet access, firewall, proxy and TLS settings."


def status_detail(status: int) -> str:
    return {
        400: "Check the selected model's request format and structured-output support.",
        401: "Authentication failed. Check OPENROUTER_API_KEY in backend/.env.",
        402: "Check OpenRouter credits and the API key spending limit.",
        403: "Access denied. Check account permissions and model access.",
        404: "Model or compatible provider not found. Check OPENROUTER_MODEL and structured-output support.",
        408: "Request timed out. Retry later.",
        429: "Rate limit reached. Wait before retrying or select another available model.",
    }.get(status, "Provider unavailable. Retry later." if status >= 500 else "Check model and account configuration.")


class OpenRouterService:
    """One bounded retry loop; no tool calling and no automatic paid fallback."""

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        if not settings.openrouter_api_key.get_secret_value():
            raise LLMError("Configure OPENROUTER_API_KEY in backend/.env")
        self.settings = settings
        try:
            self.client = client or AsyncOpenAI(
                api_key=settings.openrouter_api_key.get_secret_value(),
                base_url=settings.openrouter_base_url,
                timeout=settings.llm_timeout_seconds, max_retries=0,
            )
        except (ValueError, ImportError):
            raise LLMError("HTTP client configuration failed. Check proxy scheme and installed HTTPX/SOCKS support; credentials were not sent.") from None

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
        failure = "No valid response received."
        for attempt in range(self.settings.llm_max_attempts):
            try:
                # Outer timeout bounds the entire attempt in addition to SDK network timeouts.
                async with asyncio.timeout(self.settings.llm_timeout_seconds):
                    response = await self.client.chat.completions.create(
                        model=self.settings.openrouter_model, messages=messages,
                        max_tokens=self.settings.llm_max_output_tokens, **options,
                    )
                usage = getattr(response, "usage", None)
                tokens = {key: getattr(usage, key, None) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
                model = str(getattr(response, 'model', self.settings.openrouter_model))[:160]
                try:
                    return validate_response(response, schema)
                except OutputError as exc:
                    logging.getLogger(__name__).warning(
                        "LLM output failure schema=%s attempt=%s model=%s tokens=%s reason=%s",
                        schema.__name__, attempt + 1, model, tokens, str(exc))
                    raise
            except APIStatusError as exc:
                failure = f"HTTP {exc.status_code}: {status_detail(exc.status_code)}"
                if exc.status_code not in (408, 429) and exc.status_code < 500:
                    raise LLMError(failure) from None
            except OutputError as exc:
                failure = str(exc)
                # Give bounded repair guidance without repeating potentially sensitive output.
                if not messages[-1]["content"].startswith("The previous response"):
                    messages.append({"role": "user", "content": "The previous response failed validation: " + failure + " Return a complete JSON object matching the system schema, with no markdown or extra keys."})
                else:
                    messages[-1]["content"] = "The previous response failed validation: " + failure + " Return only valid JSON matching the system schema."
            except (APITimeoutError, TimeoutError):
                failure = "Request timed out. Retry or increase LLM_TIMEOUT_SECONDS (maximum 120)."
            except APIConnectionError as exc:
                failure = connection_detail(exc)
            if attempt + 1 < self.settings.llm_max_attempts:
                await asyncio.sleep(min(2 ** attempt, 4))
        raise LLMError("OpenRouter failed within the configured attempts. " + failure)
