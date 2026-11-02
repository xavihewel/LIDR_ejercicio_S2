"""Contrato del wrapper LiteLLM sin llamadas externas."""
import unittest
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.services.llm_provider import complete


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_both_providers_with_their_own_key_and_model(self):
        for provider, model in (("openai", "gpt-4o-mini"), ("anthropic", "claude-test")):
            for streaming in (False, True):
                with self.subTest(provider=provider, streaming=streaming):
                    settings = Settings(
                        _env_file=None, llm_provider=provider, llm_model=model,
                        openai_api_key="openai-test", anthropic_api_key="anthropic-test",
                    )
                    messages = [{"role": "user", "content": "Reunión"}]
                    with patch("app.services.llm_provider.acompletion", new_callable=AsyncMock) as call:
                        response = await complete(settings, messages, stream=streaming)
                    self.assertIs(response, call.return_value)
                    expected = dict(
                        model=model, custom_llm_provider=provider,
                        api_key=f"{provider}-test", messages=messages, stream=streaming,
                    )
                    if streaming:
                        expected["stream_options"] = {"include_usage": True}
                    call.assert_awaited_once_with(**expected)

    async def test_missing_selected_key_fails_without_provider_call(self):
        settings = Settings(_env_file=None, llm_provider="openai", openai_api_key="test")
        settings.openai_api_key = None
        with patch("app.services.llm_provider.acompletion", new_callable=AsyncMock) as call:
            with self.assertRaises(ValueError):
                await complete(settings, [])
            call.assert_not_awaited()
