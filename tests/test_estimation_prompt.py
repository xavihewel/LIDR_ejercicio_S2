"""Contrato de las plantillas de estimación, sin llamadas al LLM."""
import unittest
from unittest.mock import patch

from jinja2 import DictLoader, Environment, StrictUndefined, TemplateNotFound, UndefinedError

from app.context.examples import ESTIMATION_EXAMPLES
from app.prompts.loader import render_estimation_prompt
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType


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

    def test_narrative_selects_prose_instead_of_table_instructions(self):
        system, _ = render_estimation_prompt(self.make_request(output_format=OutputFormat.NARRATIVE))
        self.assertIn("flowing prose", system)
        self.assertNotIn("Required\ncolumns", system)

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
                    render_estimation_prompt(self.make_request())
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
