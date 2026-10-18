"""Configuración mediante variables de entorno y el .env del proyecto."""
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = "gpt-4o-mini"
    app_env: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"

    @model_validator(mode="after")
    def validate_provider_key(self) -> Self:
        key = getattr(self, f"{self.llm_provider}_api_key")
        if key is None or not key.get_secret_value().strip():
            raise ValueError(
                f"{self.llm_provider.upper()}_API_KEY es obligatoria "
                f"cuando LLM_PROVIDER={self.llm_provider}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Carga y valida la configuración al solicitarla por primera vez."""
    return Settings()
