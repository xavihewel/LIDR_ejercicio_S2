"""Extractor LLM de ProjectMetadata, sin proveedor real."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.services.metadata_extractor import extract_project_metadata
from app.services.sessions import ProjectMetadata


def _completion(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=content),
    )])


class MetadataExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings(_env_file=None, openai_api_key="test-only", cache_enabled=False)
        self.settings_patch = patch(
            "app.services.metadata_extractor.get_settings", return_value=self.settings
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.complete = patch(
            "app.services.metadata_extractor.complete", new_callable=AsyncMock
        ).start()
        self.addCleanup(patch.stopall)

    async def test_returns_metadata_parsed_from_the_extractor_json(self):
        self.complete.return_value = _completion(json.dumps({
            "project_name": "Reservas Clínica",
            "assumed_team_size": 3,
            "mentioned_technologies": ["Python", "Redis"],
            "agreed_scope": "MVP de citas",
        }))
        result = await extract_project_metadata(
            description="Transcript de la reunión sobre reservas.",
            estimation='{"phases":[]}',
            current=ProjectMetadata(),
        )
        self.assertEqual(result.project_name, "Reservas Clínica")
        self.assertEqual(result.assumed_team_size, 3)
        self.assertEqual(result.mentioned_technologies, ["Python", "Redis"])
        self.assertEqual(result.agreed_scope, "MVP de citas")
        messages = self.complete.await_args.args[1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("project_name", messages[0]["content"])
        self.assertIn("Transcript de la reunión", messages[1]["content"])
        self.assertIn('"phases":[]', messages[1]["content"])

    async def test_accepts_fenced_json_and_keeps_current_on_invalid_output(self):
        self.complete.return_value = _completion(
            "```json\n"
            + json.dumps({
                "project_name": "Inventario",
                "assumed_team_size": 2,
                "mentioned_technologies": ["FastAPI"],
                "agreed_scope": "CRUD inventario",
            })
            + "\n```"
        )
        current = ProjectMetadata(project_name="Viejo")
        result = await extract_project_metadata(
            description="Descripción suficientemente larga del inventario.",
            estimation="{}",
            current=current,
        )
        self.assertEqual(result.project_name, "Inventario")

        self.complete.return_value = _completion("no es json")
        result = await extract_project_metadata(
            description="Descripción suficientemente larga del inventario.",
            estimation="{}",
            current=current,
        )
        self.assertIs(result, current)

    async def test_provider_errors_keep_current_metadata(self):
        current = ProjectMetadata(agreed_scope="Alcance previo")
        self.complete.side_effect = RuntimeError("provider down")
        result = await extract_project_metadata(
            description="Descripción suficientemente larga del proyecto.",
            estimation="{}",
            current=current,
        )
        self.assertIs(result, current)
