from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore"
    )
    mongodb_uri: SecretStr = SecretStr("mongodb://localhost:27017")
    mongodb_database: str = "devpilot"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_structured_outputs: bool = True
    llm_timeout_seconds: float = Field(default=30, ge=1, le=120)
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    cors_origins: list[str] = ["http://localhost:5173"]
    github_token: SecretStr = SecretStr("")
    dashboard_api_token: SecretStr = SecretStr("")
    github_repository: str = ""
    repository_source: Path | None = None
    repository_allowed_files: list[str] = []
    mcp_workspace: Path | None = None
    mcp_state_dir: Path = Path(__file__).resolve().parents[1] / ".devpilot"
    mcp_timeout_seconds: float = Field(default=150, ge=10, le=240)
    sandbox_image: str = "devpilot-python-tests:phase2"
    sandbox_timeout_seconds: int = Field(default=60, ge=5, le=120)

    @field_validator("repository_source", "mcp_workspace", mode="before")
    @classmethod
    def empty_optional_path(cls, value):
        return None if value == "" else value

    @field_validator("openrouter_base_url")
    @classmethod
    def openrouter_only(cls, value: str) -> str:
        if value.rstrip("/") != "https://openrouter.ai/api/v1":
            raise ValueError("Runtime LLM calls must use https://openrouter.ai/api/v1")
        return value.rstrip("/")
