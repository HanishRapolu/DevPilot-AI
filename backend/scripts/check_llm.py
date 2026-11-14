"""Explicit opt-in live smoke test; run from backend: python -m scripts.check_llm."""
import asyncio

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.services.llm import OpenRouterService


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


if __name__ == "__main__":
    asyncio.run(main())
