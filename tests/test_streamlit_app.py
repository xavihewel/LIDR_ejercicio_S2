"""Pruebas del chat sin llamadas reales al proveedor LLM."""

from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


async def text_stream(text):
    yield text[:5]
    yield text[5:]


async def failed_stream():
    yield "Estimación parcial"
    raise RuntimeError("Respuesta incompleta")


class StreamlitChatTests(unittest.TestCase):
    def test_history_survives_reruns_and_multiple_submissions(self):
        with patch(
            "app.services.llm_service.stream_estimation",
            side_effect=lambda text: text_stream(
                "Estimación uno" if text == "Primera reunión" else "Estimación dos"
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
            generate.assert_called_with("Segunda reunión")

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
            side_effect=lambda text: failed_stream(),
        ) as generate:
            app = AppTest.from_file(str(APP)).run()
            app.chat_input[0].set_value("Una reunión").run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_message), 2)
            self.assertIn("Vuelve a intentarlo", app.chat_message[1].markdown[0].value)
            self.assertEqual(generate.call_count, 1)
