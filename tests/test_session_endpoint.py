"""Contrato HTTP para abrir una sesión en memoria."""
import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.sessions import clear_sessions, get_session


class CreateSessionEndpointTests(unittest.TestCase):
    def setUp(self):
        clear_sessions()
        self.client = TestClient(app)

    def tearDown(self):
        clear_sessions()

    def test_post_sessions_returns_a_new_uuid_v4_and_stores_it(self):
        response = self.client.post("/sessions")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"session_id"})
        session_id = body["session_id"]
        self.assertEqual(UUID(session_id).version, 4)
        stored = get_session(session_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.session_id, session_id)

    def test_each_call_creates_a_distinct_session(self):
        first = self.client.post("/sessions").json()["session_id"]
        second = self.client.post("/sessions").json()["session_id"]
        self.assertNotEqual(first, second)
        self.assertIsNot(get_session(first), get_session(second))

    def test_versioned_alias_matches_the_public_contract(self):
        response = self.client.post("/api/v1/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UUID(response.json()["session_id"]).version, 4)
