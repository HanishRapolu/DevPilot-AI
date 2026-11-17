"""Explicit opt-in live smoke test; run from backend: python -m scripts.check_llm."""
import asyncio
import socket
import sys

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.services.llm import OpenRouterService, LLMError


class SmokeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str


async def main():
    service = OpenRouterService(Settings())
    try:
        result = await service.generate("Return a short message confirming connectivity.", SmokeAnswer)
        print(result.model_dump_json())
    finally:
        await service.close()


def run_check():
    # Diagnose DNS before creating an event loop (which can itself be blocked
    # by Windows sandbox restrictions).
    try:
        socket.getaddrinfo("openrouter.ai", 443)
    except socket.gaierror:
        print("OpenRouter DNS lookup failed. Run this check in your normal terminal and check network/DNS access.")
        return 1
    try:
        asyncio.run(main())
    except LLMError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_check())
