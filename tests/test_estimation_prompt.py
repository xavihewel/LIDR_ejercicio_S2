"""Contrato de las plantillas de estimación, sin llamadas al LLM."""
import hashlib
import json
import unittest
from unittest.mock import patch

from structlog.testing import capture_logs

from jinja2 import DictLoader, Environment, StrictUndefined, TemplateNotFound, UndefinedError

from app.context.examples import ESTIMATION_EXAMPLES
from app.prompts.loader import render_estimation_prompt
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.sessions import ProjectMetadata


class EstimationPromptTests(unittest.TestCase):
    def make_request(self, **overrides):
        values = dict(
            description="Mobile app with login, chat and push notifications.",
            project_type=ProjectType.MOBILE_APP,
            detail_level=DetailLevel.DETAILED,
            output_format=OutputFormat.PHASES_TABLE,
        )
        return EstimationRequest(**(values | overrides))

    def test_estimation_prompt_includes_description_in_user_block(self):
        request = self.make_request()
        system, user = render_estimation_prompt(request)
        self.assertIn("<project_description>", user)
        self.assertIn("Mobile app with login", user)
        self.assertIn("phases_table", system)
        self.assertIn("confidence_pct", system)
        self.assertIn("</project_description>", user)
        self.assertNotIn(request.description, system)
        self.assertIn("mobile app", system)
        self.assertIn("<detail_level>detailed</detail_level>", system)

    def test_description_override_replaces_request_text_in_user_message(self):
        request = self.make_request()
        composed = request.description + "\n\n--- attachment: notes.txt ---\nAlcance"
        _, user = render_estimation_prompt(request, description=composed)
        self.assertIn("--- attachment: notes.txt ---", user)
        self.assertIn("Alcance", user)

    def test_empty_project_metadata_renders_an_empty_block(self):
        import re
        system, _ = render_estimation_prompt(self.make_request())
        self.assertRegex(system, r"<project_metadata>\s*</project_metadata>")
        self.assertNotIn("<project_name>", system)
        self.assertNotIn("<assumed_team_size>", system)
        self.assertNotIn("<mentioned_technologies>", system)
        self.assertNotIn("<agreed_scope>", system)
        self.assertIsNone(re.search(r"<project_metadata>\s*<project_", system))

    def test_project_metadata_injects_only_known_facts(self):
        metadata = ProjectMetadata(
            project_name="Reservas clínica",
            assumed_team_size=3,
            mentioned_technologies=["Python", "Redis"],
            agreed_scope="MVP con login y calendario",
        )
        system, _ = render_estimation_prompt(
            self.make_request(), project_metadata=metadata,
        )
        self.assertIn("<project_name>Reservas clínica</project_name>", system)
        self.assertIn("<assumed_team_size>3</assumed_team_size>", system)
        self.assertIn("<technology>Python</technology>", system)
        self.assertIn("<technology>Redis</technology>", system)
        self.assertIn("<agreed_scope>MVP con login y calendario</agreed_scope>", system)

        partial = ProjectMetadata(project_name="Inventario")
        system, _ = render_estimation_prompt(
            self.make_request(), project_metadata=partial,
        )
        self.assertIn("<project_name>Inventario</project_name>", system)
        self.assertNotIn("<assumed_team_size>", system)
        self.assertNotIn("<mentioned_technologies>", system)
        self.assertNotIn("<agreed_scope>", system)

    def test_narrative_selects_prose_instead_of_table_instructions(self):
        system, _ = render_estimation_prompt(
            self.make_request(output_format=OutputFormat.NARRATIVE), version="v1"
        )
        self.assertIn("flowing prose", system)
        self.assertNotIn("Required\ncolumns", system)

    def test_default_prompt_asks_for_json_matching_the_selected_format(self):
        system, user = render_estimation_prompt(self.make_request())
        self.assertIn("one JSON object", system)
        self.assertIn("total_duration_weeks", system)
        self.assertIn("JSON object only", user)
        narrative, _ = render_estimation_prompt(self.make_request(output_format=OutputFormat.NARRATIVE))
        self.assertIn('"overview"', narrative)
        self.assertNotIn("confidence_pct", narrative)

    def test_examples_are_rendered_as_context_instead_of_python_source(self):
        system, _ = render_estimation_prompt(self.make_request())
        for example in ESTIMATION_EXAMPLES:
            self.assertIn(example["meeting_summary"], system)
            self.assertIn(example["estimation"].strip(), system)
        self.assertNotIn("ESTIMATION_EXAMPLES =", system)

    def test_description_is_preserved_without_evaluating_template_syntax(self):
        description = 'Proyecto con {{ output_format }} y <API> & "chat".'
        _, user = render_estimation_prompt(self.make_request(description=description))
        self.assertIn(description, user)

    def test_unknown_version_fails_explicitly(self):
        with self.assertRaises(TemplateNotFound):
            render_estimation_prompt(self.make_request(), version="missing")

    def test_version_selects_system_user_and_examples_from_same_folder(self):
        templates = {
            f"estimation/{version}/{name}.j2": content
            for version in ("v1", "v2")
            for name, content in (
                ("system", "System " + version + " {% include examples_template %}"),
                ("user", "User " + version + " {{ description }}"),
                ("examples", "Examples " + version),
            )
        }
        environment = Environment(
            loader=DictLoader(templates), undefined=StrictUndefined,
            trim_blocks=True, lstrip_blocks=True,
        )
        with patch("app.prompts.loader._env", environment):
            for version in ("v1", "v2"):
                with self.subTest(version=version):
                    system, user = render_estimation_prompt(self.make_request(), version=version)
                    self.assertEqual(system, f"System {version} Examples {version}")
                    self.assertEqual(user, f"User {version} {self.make_request().description}")

    def test_missing_template_variable_fails_instead_of_rendering_empty_text(self):
        from app.prompts.loader import _env
        templates = {
            "estimation/v1/system.j2": "{{ missing_variable }}",
            "estimation/v1/user.j2": "{{ description }}",
        }
        with patch.object(_env, "loader", DictLoader(templates)):
            _env.cache.clear()
            try:
                with self.assertRaises(UndefinedError):
                    render_estimation_prompt(self.make_request(), version="v1")
            finally:
                _env.cache.clear()

    def test_line_items_and_summary_have_explicit_instructions(self):
        system, _ = render_estimation_prompt(self.make_request(
            project_type=ProjectType.DATA_PIPELINE,
            detail_level=DetailLevel.SUMMARY, output_format=OutputFormat.LINE_ITEMS,
        ))
        self.assertIn("data pipeline", system)
        self.assertIn("individual tasks", system)
        self.assertIn("Keep the estimate brief", system)

    def test_v1_preserves_literal_description_inside_project_description_block(self):
        descriptions = (
            "Mobile app with login, chat and push notifications.",
            '  Aplicación con {{ output_format }}, <API> & "chat".\nSegunda línea.  ',
        )
        for description in descriptions:
            with self.subTest(description=description):
                _, user = render_estimation_prompt(
                    self.make_request(description=description), version="v1"
                )
                _, opening, rest = user.partition("<project_description>\n")
                content, closing, _ = rest.partition("\n</project_description>")
                self.assertTrue(opening)
                self.assertTrue(closing)
                self.assertEqual(content, description)

    def test_v1_table_keywords_are_present_only_for_phases_table(self):
        for output_format, expected in (
            (OutputFormat.PHASES_TABLE, True), (OutputFormat.NARRATIVE, False),
        ):
            with self.subTest(output_format=output_format):
                system, _ = render_estimation_prompt(
                    self.make_request(output_format=output_format), version="v1"
                )
                for keyword in ("phases_table", "confidence_pct"):
                    self.assertEqual(keyword in system, expected)

    def test_v1_per_phase_assumptions_instruction_is_present_only_for_detailed(self):
        instruction = "For every phase, list the assumptions you made"
        for detail_level, expected in (
            (DetailLevel.DETAILED, True), (DetailLevel.SUMMARY, False),
        ):
            with self.subTest(detail_level=detail_level):
                system, _ = render_estimation_prompt(
                    self.make_request(detail_level=detail_level), version="v1"
                )
                self.assertEqual(instruction in system, expected)

    def test_render_logs_version_and_hash_without_prompt_content(self):
        with capture_logs() as events:
            system, user = render_estimation_prompt(self.make_request(), version="v1")
        self.assertEqual(len(events), 1)
        raw = json.dumps({"system": system, "user": user}, ensure_ascii=False, sort_keys=True)
        self.assertEqual(events[0], {
            "event": "prompt_rendered", "prompt_version": "v1",
            "prompt_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "log_level": "info",
        })
        self.assertNotIn(self.make_request().description, json.dumps(events))

    def test_prompt_hash_is_stable_and_changes_with_either_message(self):
        from app.prompts.loader import _env
        templates = {
            "estimation/v1/system.j2": "System {{ output_format }}",
            "estimation/v1/user.j2": "User {{ description }}",
        }
        with patch.object(_env, "loader", DictLoader(templates)), capture_logs() as events:
            _env.cache.clear()
            try:
                render_estimation_prompt(self.make_request(), version="v1")
                render_estimation_prompt(self.make_request(), version="v1")
                render_estimation_prompt(
                    self.make_request(description="Another mobile application with chat."), version="v1"
                )
                render_estimation_prompt(
                    self.make_request(output_format=OutputFormat.NARRATIVE), version="v1"
                )
            finally:
                _env.cache.clear()
        hashes = [event["prompt_hash"] for event in events]
        self.assertEqual(hashes[0], hashes[1])
        self.assertNotEqual(hashes[0], hashes[2])
        self.assertNotEqual(hashes[0], hashes[3])

    def test_failed_render_does_not_emit_success_event(self):
        with capture_logs() as events:
            with self.assertRaises(TemplateNotFound):
                render_estimation_prompt(self.make_request(), version="missing")
        self.assertEqual(events, [])
