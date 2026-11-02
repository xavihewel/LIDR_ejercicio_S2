"""Contrato HTTP validado antes de llamar al servicio LLM."""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from litellm.exceptions import AuthenticationError, Timeout

from app.main import app
from app.schemas import EstimationRequest
from app.prompts.loader import render_estimation_prompt

PAYLOAD = {
    "description": "Aplicación móvil con login, chat y notificaciones push.",
    "project_type": "mobile_app", "detail_level": "detailed", "output_format": "phases_table",
}


class EstimationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        service = patch("app.routers.estimations.generate_estimation", new_callable=AsyncMock, return_value="Texto libre de estimación")
        self.service = service.start()
        self.addCleanup(service.stop)

    def test_returns_free_text_and_prompt_version(self):
        response = self.client.post("/estimate", json=PAYLOAD)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "Texto libre de estimación", "prompt_version": "v1"})
        request = EstimationRequest.model_validate(PAYLOAD)
        self.service.assert_awaited_once_with(request, prompt=render_estimation_prompt(request))

    def test_invalid_contract_does_not_call_llm(self):
        for extra in (
            {"description": "short"}, {"description": "x" * 2001},
            {"description": " " * 20}, {"description": None}, {"description": 123},
            {"project_type": "unknown"}, {"detail_level": "unknown"}, {"output_format": "unknown"},
        ):
            with self.subTest(extra=extra):
                self.assertEqual(self.client.post("/estimate", json=PAYLOAD | extra).status_code, 422)
        for missing in PAYLOAD:
            self.assertEqual(self.client.post("/estimate", json={k: v for k, v in PAYLOAD.items() if k != missing}).status_code, 422)
        self.service.assert_not_awaited()

    def test_provider_and_configuration_errors_are_generic(self):
        for error, status in (
            (RuntimeError("private details"), 502), (ValueError("private details"), 503),
            (Timeout(message="private details", model="test", llm_provider="anthropic"), 504),
            (AuthenticationError(message="private details", model="test", llm_provider="openai"), 502),
        ):
            with self.subTest(status=status):
                self.service.side_effect = error
                response = self.client.post("/estimate", json=PAYLOAD)
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private details", response.text)

    def test_description_length_boundaries_are_accepted(self):
        for size in (20, 2000):
            with self.subTest(size=size):
                response = self.client.post("/estimate", json=PAYLOAD | {"description": "x" * size})
                self.assertEqual(response.status_code, 200)

    def test_endpoint_renders_prompt_and_passes_separate_messages_to_service(self):
        with patch("app.routers.estimations.render_estimation_prompt", return_value=("System rules", "User description")) as render:
            response = self.client.post("/estimate", json=PAYLOAD)
        self.assertEqual(response.status_code, 200)
        request = EstimationRequest.model_validate(PAYLOAD)
        render.assert_called_once_with(request)
        self.service.assert_awaited_once_with(request, prompt=("System rules", "User description"))


class EndpointProviderIntegrationTests(unittest.TestCase):
    def test_rendered_prompt_reaches_existing_provider_wrapper(self):
        from types import SimpleNamespace
        from app.config import Settings
        settings = Settings(_env_file=None, openai_api_key="test", cache_enabled=False)
        result = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content="Texto libre")
        )])
        with patch("app.routers.estimations.render_estimation_prompt", return_value=("System rules", "User description")) as render, patch(
            "app.services.llm_service.get_settings", return_value=settings
        ), patch("app.services.llm_service.render_estimation_prompt") as second_render, patch(
            "app.services.llm_service.complete", new_callable=AsyncMock, return_value=result
        ) as complete:
            response = TestClient(app).post("/estimate", json=PAYLOAD)
        self.assertEqual(response.json(), {"text": "Texto libre", "prompt_version": "v1"})
        render.assert_called_once()
        second_render.assert_not_called()
        complete.assert_awaited_once_with(settings, [
            {"role": "system", "content": "System rules"},
            {"role": "user", "content": "User description"},
        ])
