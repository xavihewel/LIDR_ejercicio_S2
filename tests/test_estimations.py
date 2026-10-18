"""Pruebas HTTP del endpoint sin llamadas reales al proveedor."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


class EstimationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        settings_patch = patch(
            "app.routers.estimations.get_settings",
            return_value=SimpleNamespace(llm_model="gpt-4o-mini", llm_provider="openai"),
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        service_patch = patch(
            "app.routers.estimations.generate_estimation",
            new_callable=AsyncMock,
            return_value="## Estimación: Plataforma web\n\n### Desglose de tareas:\n...",
        )
        self.service = service_patch.start()
        self.addCleanup(service_patch.stop)

    def test_returns_estimation_and_model_metadata(self):
        response = self.client.post(
            "/api/v1/estimate", json={"transcription": "Necesitamos una plataforma web."}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "estimation": self.service.return_value,
            "model": "gpt-4o-mini",
            "provider": "openai",
        })
        self.service.assert_awaited_once_with("Necesitamos una plataforma web.")

    def test_invalid_requests_do_not_call_llm(self):
        for body in ({}, {"transcription": ""}, {"transcription": " \n "},
                     {"transcription": None}, {"transcription": 123}):
            with self.subTest(body=body):
                response = self.client.post("/api/v1/estimate", json=body)
                self.assertEqual(response.status_code, 422)
        self.service.assert_not_awaited()

    def test_provider_failure_returns_generic_error(self):
        self.service.side_effect = RuntimeError("Internal provider details")
        response = self.client.post("/api/v1/estimate", json={"transcription": "Reunión"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("Internal provider details", response.text)

    def test_configuration_failure_returns_unavailable(self):
        self.service.side_effect = ValueError("Missing API key")
        response = self.client.post("/api/v1/estimate", json={"transcription": "Reunión"})
        self.assertEqual(response.status_code, 503)
