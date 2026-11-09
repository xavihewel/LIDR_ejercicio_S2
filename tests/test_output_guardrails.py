"""Guardrails de la salida del modelo, sin red ni Redis."""
import json
import unittest

from pydantic import ValidationError

from app.schemas import (
    EstimationRequest,
    EstimationResponse,
    LineItemsEstimate,
    NarrativeEstimate,
    OutputFormat,
    PhasesTableEstimate,
    ProjectType,
    DetailLevel,
)
from app.services.output_guardrails import build_estimation_response, parse_estimation


PHASES = {
    "phases": [
        {"phase": "Diseño", "duration_weeks": 2, "cost_eur": 1000, "confidence_pct": 70},
        {"phase": "Desarrollo", "duration_weeks": 4, "cost_eur": 4000, "confidence_pct": 60},
    ],
    "total_duration_weeks": 6,
}
LINE_ITEMS = {
    "items": [
        {"task": "API", "hours": 10, "assumptions": "Alcance cerrado", "risks": "Integraciones"},
        {"task": "Pruebas", "hours": 5, "assumptions": "Entorno disponible", "risks": "Datos incompletos"},
    ],
    "total_hours": 15,
}
NARRATIVE = {
    "overview": "Aplicación móvil con acceso y avisos.",
    "breakdown": "El trabajo se concentra en API, clientes y pruebas.",
    "risks": "Las notificaciones dependen de credenciales de terceros.",
}


def request(output_format=OutputFormat.PHASES_TABLE):
    return EstimationRequest(
        description="Aplicación móvil con login, chat y notificaciones push.",
        project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED,
        output_format=output_format,
    )


class ParseEstimationTests(unittest.TestCase):
    def test_accepts_json_for_each_format(self):
        cases = (
            (OutputFormat.PHASES_TABLE, PHASES, PhasesTableEstimate),
            (OutputFormat.LINE_ITEMS, LINE_ITEMS, LineItemsEstimate),
            (OutputFormat.NARRATIVE, NARRATIVE, NarrativeEstimate),
        )
        for output_format, payload, model in cases:
            with self.subTest(output_format=output_format):
                parsed = parse_estimation(json.dumps(payload), output_format)
                self.assertIsInstance(parsed, model)

    def test_accepts_a_single_json_fence(self):
        raw = "```json\n" + json.dumps(PHASES) + "\n```"
        parsed = parse_estimation(raw, OutputFormat.PHASES_TABLE)
        self.assertEqual(parsed.total_duration_weeks, 6)

    def test_rejects_prose_blank_text_and_mismatched_totals(self):
        mismatched_phases = json.dumps(PHASES | {"total_duration_weeks": 9})
        mismatched_items = json.dumps(LINE_ITEMS | {"total_hours": 40})
        blank_narrative = json.dumps(NARRATIVE | {"risks": "   "})
        for raw, output_format in (
            ("Texto libre", OutputFormat.PHASES_TABLE),
            ("", OutputFormat.PHASES_TABLE),
            ("```json\nno-json\n```", OutputFormat.PHASES_TABLE),
            (mismatched_phases, OutputFormat.PHASES_TABLE),
            (mismatched_items, OutputFormat.LINE_ITEMS),
            (blank_narrative, OutputFormat.NARRATIVE),
            (json.dumps(LINE_ITEMS), OutputFormat.PHASES_TABLE),
        ):
            with self.subTest(output_format=output_format, raw=raw):
                with self.assertRaises(RuntimeError):
                    parse_estimation(raw, output_format)

    def test_schema_rejects_a_response_without_the_selected_body(self):
        with self.assertRaises(ValidationError):
            EstimationResponse(
                text="## Estimación", prompt_version="v2",
                output_format=OutputFormat.PHASES_TABLE,
            )

    def test_response_renders_markdown_from_the_validated_body(self):
        response = build_estimation_response(json.dumps(PHASES), request(), "v2")
        self.assertEqual(response.prompt_version, "v2")
        self.assertEqual(response.output_format, OutputFormat.PHASES_TABLE)
        self.assertEqual(response.phases_table.total_duration_weeks, 6)
        self.assertIsNone(response.line_items)
        self.assertIsNone(response.narrative)
        self.assertIn("Diseño", response.text)
        self.assertIn("6", response.text)

        items = build_estimation_response(
            json.dumps(LINE_ITEMS), request(OutputFormat.LINE_ITEMS), "v2"
        )
        self.assertIn("API", items.text)
        self.assertIn("15", items.text)
        self.assertIsNone(items.phases_table)

        narrative = build_estimation_response(
            json.dumps(NARRATIVE), request(OutputFormat.NARRATIVE), "v2"
        )
        self.assertIn(NARRATIVE["overview"], narrative.text)
        self.assertIn(NARRATIVE["risks"], narrative.text)
        self.assertIsNone(narrative.phases_table)
