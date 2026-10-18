"""Verifica el estado de la API y su configuración pública."""
import unittest

from fastapi.testclient import TestClient

from app.main import app


class AppTests(unittest.TestCase):
    def test_health(self):
        with TestClient(app) as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_documentation_and_versioned_route(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/docs").status_code, 200)
            schema = client.get("/openapi.json").json()
        self.assertEqual(schema["info"]["title"], "Estimador CAG")
        self.assertTrue(schema["info"]["description"])
        self.assertIn("post", schema["paths"]["/api/v1/estimate"])
        self.assertIn("get", schema["paths"]["/health"])
        self.assertNotIn("/api/v1/api/v1/estimate", schema["paths"])
