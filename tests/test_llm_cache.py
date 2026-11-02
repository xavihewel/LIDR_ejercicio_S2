"""Contrato de caché exact-match sin servidor Redis externo."""
import unittest
from unittest.mock import AsyncMock, patch

from app.services.llm_cache import CachedEstimation, LLMCache


class CacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cache = LLMCache("redis://localhost:6379", ttl=123)
        self.messages = [{"role": "system", "content": "Reglas"}, {"role": "user", "content": "Reunión"}]
        self.factory = patch("app.services.llm_cache.Redis.from_url").start()
        self.addCleanup(patch.stopall)
        self.redis = self.factory.return_value.__aenter__.return_value
        self.redis.get = AsyncMock(return_value=None)
        self.redis.setex = AsyncMock()

    def test_key_matches_exact_input_and_separates_provider_model_and_context(self):
        key = self.cache.cache_key(self.messages, "model", "openai")
        self.assertEqual(key, self.cache.cache_key(self.messages, "model", "openai"))
        for messages, model, provider in (
            (self.messages, "other", "openai"), (self.messages, "model", "anthropic"),
            ([{**m, "content": m["content"] + " "} for m in self.messages], "model", "openai"),
            ([{"role": "system", "content": "Otras reglas"}, self.messages[1]], "model", "openai"),
        ):
            self.assertNotEqual(key, self.cache.cache_key(messages, model, provider))
        self.assertNotIn("Reunión", key)

    async def test_round_trip_uses_configured_ttl(self):
        entry = CachedEstimation(content="Resultado", model="resolved", tokens_in=12, tokens_out=3)
        await self.cache.set("key", entry)
        key, ttl, raw = self.redis.setex.call_args.args
        self.assertEqual((key, ttl), ("key", 123))
        self.redis.get.return_value = raw
        self.assertEqual(await self.cache.get("key"), entry)

    async def test_miss_corruption_and_unavailable_redis_allow_generation(self):
        from redis.exceptions import ConnectionError
        for value in (None, "broken", '{}', '{"content":"","model":"x"}'):
            self.redis.get.return_value = value
            self.assertIsNone(await self.cache.get("key"))
        self.redis.get.side_effect = ConnectionError("offline")
        self.assertIsNone(await self.cache.get("key"))
        self.redis.setex.side_effect = ConnectionError("offline")
        await self.cache.set("key", CachedEstimation(content="OK", model="model"))
