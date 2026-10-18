"""Verificaciones del contrato CAG sin llamadas reales a OpenAI."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import generate_estimation


class GenerateEstimationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings(_env_file=None, openai_api_key="test-only", llm_provider="openai")
        self.settings_patch = patch(
            "app.services.llm_service.get_settings", return_value=self.settings
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.client_patch = patch("app.services.llm_service.AsyncOpenAI")
        self.client_factory = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.client = self.client_factory.return_value.__aenter__.return_value
        self.create = AsyncMock()
        self.client.chat.completions.create = self.create
        self.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content="Estimación generada")
        )])

    async def test_sends_examples_and_transcription_in_separate_roles(self):
        transcript = "Necesitamos una aplicación para gestionar cursos."
        self.assertEqual(await generate_estimation(transcript), "Estimación generada")
        request = self.create.call_args.kwargs
        self.assertEqual(request["model"], self.settings.llm_model)
        system, user = request["messages"]
        self.assertEqual(system["role"], "system")
        self.assertEqual(user, {"role": "user", "content": transcript})
        for example in ESTIMATION_EXAMPLES:
            self.assertIn(example["meeting_summary"], system["content"])
            self.assertIn(example["estimation"].strip(), system["content"])

    async def test_rejects_blank_transcription_without_calling_api(self):
        with self.assertRaises(ValueError):
            await generate_estimation(" \n ")
        self.client_factory.assert_not_called()

    async def test_rejects_unsupported_provider(self):
        self.settings.llm_provider = "anthropic"
        with self.assertRaises(ValueError):
            await generate_estimation("Una reunión")
        self.client_factory.assert_not_called()

    async def test_rejects_empty_or_incomplete_responses(self):
        for choices in (
            [],
            [SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="Parcial"))],
            [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=None))],
        ):
            with self.subTest(choices=choices):
                self.create.return_value = SimpleNamespace(choices=choices)
                with self.assertRaises(RuntimeError):
                    await generate_estimation("Una reunión")
