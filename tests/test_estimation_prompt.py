"""Contrato de las plantillas de estimación, sin llamadas al LLM."""
import unittest

from jinja2 import TemplateNotFound

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
