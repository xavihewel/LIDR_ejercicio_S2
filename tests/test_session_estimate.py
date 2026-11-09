"""POST /sessions/{id}/estimate con transcript y adjuntos (camino B)."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.prompts.loader import render_estimation_prompt
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.sessions import ProjectMetadata, clear_sessions, get_session


EXTRACTED = ProjectMetadata(
    project_name="Reservas Clínica",
    assumed_team_size=3,
    mentioned_technologies=["Python"],
    agreed_scope="MVP de citas",
)

PHASES = json.dumps({
    "phases": [
        {"phase": "Diseño", "duration_weeks": 2, "cost_eur": 1000, "confidence_pct": 70},
        {"phase": "Desarrollo", "duration_weeks": 4, "cost_eur": 4000, "confidence_pct": 60},
    ],
    "total_duration_weeks": 6,
}, ensure_ascii=False)

TRANSCRIPT = "Aplicación móvil con login, chat y notificaciones push."
FORM = {
    "transcript": TRANSCRIPT,
    "project_type": "mobile_app",
    "detail_level": "detailed",
    "output_format": "phases_table",
}


class SessionEstimateEndpointTests(unittest.TestCase):
    def setUp(self):
        clear_sessions()
        self.client = TestClient(app)
        service = patch(
            "app.routers.estimations.generate_estimation",
            new_callable=AsyncMock,
            return_value=PHASES,
        )
        self.service = service.start()
        self.addCleanup(service.stop)
        extractor = patch(
            "app.routers.estimations.extract_project_metadata",
            new_callable=AsyncMock,
            return_value=EXTRACTED,
        )
        self.extractor = extractor.start()
        self.addCleanup(extractor.stop)
        self.addCleanup(clear_sessions)
        self.session_id = self.client.post("/sessions").json()["session_id"]

    def test_unknown_session_returns_404_without_calling_llm(self):
        response = self.client.post("/sessions/missing/estimate", data=FORM)
        self.assertEqual(response.status_code, 404)
        self.service.assert_not_awaited()

    def test_invalid_transcript_returns_422_without_calling_llm(self):
        response = self.client.post(
            f"/sessions/{self.session_id}/estimate",
            data=FORM | {"transcript": "corto"},
        )
        self.assertEqual(response.status_code, 422)
        self.service.assert_not_awaited()

    def test_unsupported_attachment_returns_422_without_calling_llm(self):
        response = self.client.post(
            f"/sessions/{self.session_id}/estimate",
            data=FORM,
            files=[("attachments", ("payload.exe", b"MZ", "application/octet-stream"))],
        )
        self.assertEqual(response.status_code, 422)
        self.service.assert_not_awaited()

    def test_without_attachments_uses_transcript_and_stores_history(self):
        response = self.client.post(f"/sessions/{self.session_id}/estimate", data=FORM)
        self.assertEqual(response.status_code, 200)
        request = EstimationRequest(
            description=TRANSCRIPT,
            project_type=ProjectType.MOBILE_APP,
            detail_level=DetailLevel.DETAILED,
            output_format=OutputFormat.PHASES_TABLE,
        )
        messages = self.service.await_args.kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn(TRANSCRIPT, messages[-1]["content"])
        system, _ = render_estimation_prompt(
            request, description=TRANSCRIPT, project_metadata=ProjectMetadata(),
        )
        self.assertEqual(messages[0]["content"], system)
        history = get_session(self.session_id).history.messages
        self.assertEqual(len(history), 3)
        self.assertIn(TRANSCRIPT, history[1]["content"])
        self.extractor.assert_awaited_once()
        self.assertEqual(get_session(self.session_id).metadata, EXTRACTED)

    def test_session_metadata_is_injected_into_the_system_prompt(self):
        session = get_session(self.session_id)
        session.metadata = ProjectMetadata(
            project_name="Reservas clínica",
            assumed_team_size=2,
            mentioned_technologies=["FastAPI"],
            agreed_scope="MVP de citas",
        )
        response = self.client.post(f"/sessions/{self.session_id}/estimate", data=FORM)
        self.assertEqual(response.status_code, 200)
        system = self.service.await_args.kwargs["messages"][0]["content"]
        self.assertIn("<project_name>Reservas clínica</project_name>", system)
        self.assertIn("<assumed_team_size>2</assumed_team_size>", system)
        self.assertIn("<technology>FastAPI</technology>", system)
        self.assertIn("<agreed_scope>MVP de citas</agreed_scope>", system)

    def test_attachments_are_extracted_and_appended_to_the_prompt(self):
        response = self.client.post(
            f"/sessions/{self.session_id}/estimate",
            data=FORM,
            files=[("attachments", ("notes.txt", b"Alcance del MVP", "text/plain"))],
        )
        self.assertEqual(response.status_code, 200)
        request = self.service.await_args.args[0]
        user = self.service.await_args.kwargs["messages"][-1]["content"]
        self.assertEqual(request.description, TRANSCRIPT)
        self.assertIn(TRANSCRIPT, user)
        self.assertIn("--- attachment: notes.txt ---", user)
        self.assertIn("Alcance del MVP", user)
        history_user = get_session(self.session_id).history.messages[1]["content"]
        self.assertIn("--- attachment: notes.txt ---", history_user)
