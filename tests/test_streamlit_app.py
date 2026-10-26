"""Pruebas del chat sin llamadas reales al proveedor LLM."""

from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.services.llm_service import build_system_prompt
from app.context.examples import ESTIMATION_EXAMPLES


APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


async def text_stream(text, metrics):
    metrics.model = "test-model"
    metrics.input_tokens = 123
    metrics.output_tokens = 45
    metrics.response_seconds = 1.25
    yield text[:5]
    yield text[5:]


async def failed_stream():
    yield "Estimación parcial"
    raise RuntimeError("Respuesta incompleta")


class StreamlitChatTests(unittest.TestCase):
    def test_sidebar_shows_exact_prompt_and_examples_before_any_call(self):
        app = AppTest.from_file(str(APP)).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.sidebar.code[0].value, build_system_prompt())
        context = "\n".join(item.value for item in app.sidebar.markdown)
        for example in ESTIMATION_EXAMPLES:
            self.assertIn(example["meeting_summary"], context)
            self.assertIn(" ".join(example["estimation"].split()), " ".join(context.split()))
        self.assertEqual(len(app.sidebar.metric), 0)

    def test_history_survives_reruns_and_multiple_submissions(self):
        with patch(
            "app.services.llm_service.stream_estimation",
            side_effect=lambda text, metrics: text_stream(
                "Estimación uno" if text == "Primera reunión" else "Estimación dos", metrics
            ),
        ) as generate:
            app = AppTest.from_file(str(APP)).run()
            self.assertFalse(app.exception)
            app.chat_input[0].set_value("Primera reunión").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_message), 2)
            self.assertEqual(app.chat_message[1].markdown[0].value, "Estimación uno")
            app.run()
            self.assertEqual(len(app.chat_message), 2)
            self.assertEqual(generate.call_count, 1)
            app.chat_input[0].set_value("Segunda reunión").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_message), 4)
            self.assertEqual(app.session_state["messages"][-1], {
                "role": "assistant", "content": "Estimación dos"
            })
            self.assertEqual(generate.call_args.args, ("Segunda reunión",))
            self.assertEqual([m.value for m in app.sidebar.metric], ["test-model", "123", "45", "1.25 s"])
            app.run()
            self.assertEqual(app.sidebar.metric[0].value, "test-model")

    def test_blank_input_does_not_call_llm(self):
        with patch(
            "app.services.llm_service.stream_estimation"
        ) as generate:
            app = AppTest.from_file(str(APP)).run()
            app.chat_input[0].set_value("   ").run()
            self.assertFalse(app.exception)
            generate.assert_not_called()
            self.assertEqual(app.session_state["messages"], [])

    def test_provider_failure_is_visible_after_rerun(self):
        with patch(
            "app.services.llm_service.stream_estimation",
            side_effect=lambda text, metrics: failed_stream(),
        ) as generate:
            app = AppTest.from_file(str(APP)).run()
            app.chat_input[0].set_value("Una reunión").run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_message), 2)
            self.assertIn("Vuelve a intentarlo", app.chat_message[1].markdown[0].value)
            self.assertEqual(generate.call_count, 1)

    def test_failed_call_replaces_previous_metrics_with_unavailable_values(self):
        with patch(
            "app.services.llm_service.stream_estimation",
            side_effect=lambda text, metrics: (
                text_stream("Estimación correcta", metrics)
                if text == "Primera reunión" else failed_stream()
            ),
        ):
            app = AppTest.from_file(str(APP)).run()
            app.chat_input[0].set_value("Primera reunión").run()
            self.assertEqual(
                [m.value for m in app.sidebar.metric],
                ["test-model", "123", "45", "1.25 s"],
            )
            app.chat_input[0].set_value("Segunda reunión").run()
            self.assertFalse(app.exception)
            self.assertEqual([m.value for m in app.sidebar.metric], ["No disponible"] * 4)
            app.run()
            self.assertEqual([m.value for m in app.sidebar.metric], ["No disponible"] * 4)
            self.assertEqual(len(app.chat_message), 4)
