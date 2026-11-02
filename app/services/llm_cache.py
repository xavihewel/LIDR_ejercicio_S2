"""Caché Redis exact-match compartida por FastAPI y Streamlit."""

import hashlib
import json
import structlog

from pydantic import BaseModel, Field, ValidationError, field_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)


class CachedEstimation(BaseModel):
    content: str
    model: str
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("La estimación debe contener texto.")
        return value


class LLMCache:
    def __init__(self, redis_url: str = "redis://localhost:6379", ttl: int = 86400):
        self.redis_url = redis_url
        self.ttl = ttl

    @staticmethod
    def cache_key(messages: list, model: str, provider: str) -> str:
        raw = json.dumps(
            {"messages": messages, "model": model, "provider": provider},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        return f"llm:v1:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def _client(self) -> Redis:
        # Clientes por operación para soportar los distintos event loops de Streamlit.
        return Redis.from_url(
            self.redis_url, decode_responses=True,
            socket_connect_timeout=0.5, socket_timeout=0.5,
        )

    async def get(self, key: str) -> CachedEstimation | None:
        try:
            async with self._client() as client:
                raw = await client.get(key)
            result = CachedEstimation.model_validate_json(raw) if raw is not None else None
            logger.info("cache_hit" if result is not None else "cache_miss")
            return result
        except (RedisError, ValidationError, UnicodeError) as exc:
            logger.warning("cache_read_failed", error_type=type(exc).__name__)
            return None

    async def set(self, key: str, result: CachedEstimation) -> None:
        try:
            async with self._client() as client:
                await client.setex(key, self.ttl, result.model_dump_json())
        except RedisError as exc:
            logger.warning("cache_write_failed", error_type=type(exc).__name__)
        else:
            logger.info("cache_stored", ttl_seconds=self.ttl)
