"""El formulario valida y envía el contrato JSON al servicio HTTP."""
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
DESCRIPTION = "Aplicación móvil con login, chat y notificaciones push."


class StreamlitFormTests(unittest.TestCase):
    def response(self, status=200, body=None):
        return httpx.Response(status, json=body or {"text": "## Estimación libre", "prompt_version": "v1"}, request=httpx.Request("POST", "http://localhost/estimate"))

    def test_submission_posts_validated_json_and_keeps_result_on_rerun(self):
        with patch("httpx.post", return_value=self.response()) as post:
            app = AppTest.from_file(str(APP)).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_input), 0)
            self.assertEqual(len(app.text_area), 1)
            self.assertEqual(len(app.selectbox), 3)
            app.text_area[0].set_value(DESCRIPTION)
            app.selectbox[0].select("mobile_app")
            app.selectbox[1].select("detailed")
            app.selectbox[2].select("phases_table")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(post.call_args.kwargs["json"], {
                "description": DESCRIPTION, "project_type": "mobile_app",
                "detail_level": "detailed", "output_format": "phases_table",
            })
            self.assertTrue(post.call_args.args[0].endswith("/estimate"))
            self.assertIn("## Estimación libre", [item.value for item in app.markdown])
            app.run()
            self.assertEqual(post.call_count, 1)
            self.assertIn("## Estimación libre", [item.value for item in app.markdown])

    def test_invalid_description_never_calls_http(self):
        with patch("httpx.post") as post:
            app = AppTest.from_file(str(APP)).run()
            for text in ("", "corto", " " * 25):
                app.text_area[0].set_value(text)
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
            post.assert_not_called()

    def test_http_errors_and_invalid_responses_are_displayed(self):
        for result in (self.response(422), self.response(503), self.response(body={"unexpected": True}), httpx.ConnectError("offline"), httpx.ReadTimeout("slow")):
            with self.subTest(result=result), patch("httpx.post") as post:
                if isinstance(result, Exception):
                    post.side_effect = result
                else:
                    post.return_value = result
                app = AppTest.from_file(str(APP)).run()
                app.text_area[0].set_value(DESCRIPTION)
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)

    def test_form_posts_to_real_fastapi_contract_without_llm_network(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as api, patch(
            "app.routers.estimations.generate_estimation", return_value="Resultado del servicio"
        ) as generate, patch("httpx.post", side_effect=lambda url, **kwargs: api.post("/estimate", json=kwargs["json"])):
            app_test = AppTest.from_file(str(APP)).run()
            app_test.text_area[0].set_value(DESCRIPTION)
            app_test.selectbox[0].select("web_saas")
            app_test.selectbox[1].select("summary")
            app_test.selectbox[2].select("line_items")
            app_test.button[0].click().run()
            self.assertFalse(app_test.exception)
            self.assertIn("Resultado del servicio", [item.value for item in app_test.markdown])
            request = generate.call_args.args[0]
            self.assertEqual(request.project_type.value, "web_saas")
            self.assertEqual(request.detail_level.value, "summary")
            self.assertEqual(request.output_format.value, "line_items")

    def test_api_url_is_configurable_without_llm_credentials(self):
        with patch.dict("os.environ", {"ESTIMATION_API_URL": "http://service:9000/"}), patch("httpx.post", return_value=self.response()) as post:
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(DESCRIPTION)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(post.call_args.args[0], "http://service:9000/estimate")
