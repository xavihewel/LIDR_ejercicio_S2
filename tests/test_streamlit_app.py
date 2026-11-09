"""El formulario valida y envía multipart al servicio HTTP."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from streamlit.testing.v1 import AppTest

from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.output_guardrails import build_estimation_response
from app.services.sessions import ProjectMetadata

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
DESCRIPTION = "Aplicación móvil con login, chat y notificaciones push."
SESSION_ID = "11111111-1111-4111-8111-111111111111"
NEW_SESSION_ID = "22222222-2222-4222-8222-222222222222"
PHASES = json.dumps({
    "phases": [{"phase": "Diseño", "duration_weeks": 2, "cost_eur": 1000, "confidence_pct": 70}],
    "total_duration_weeks": 2,
}, ensure_ascii=False)
LINE_ITEMS = json.dumps({
    "items": [{"task": "API", "hours": 10, "assumptions": "Alcance cerrado", "risks": "Integraciones"}],
    "total_hours": 10,
}, ensure_ascii=False)
EXTRACTED_METADATA = {
    "project_name": "App móvil",
    "assumed_team_size": 2,
    "mentioned_technologies": ["Flutter"],
    "agreed_scope": "Login, chat y push",
}


def _request(output_format=OutputFormat.PHASES_TABLE):
    return EstimationRequest(
        description=DESCRIPTION, project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED, output_format=output_format,
    )


def _json_response(method, url, body, status=200):
    return httpx.Response(status, json=body, request=httpx.Request(method, url))


def _click_submit(app: AppTest) -> AppTest:
    return next(button for button in app.button if button.label == "Enviar").click().run()


def _click_new_conversation(app: AppTest) -> AppTest:
    return next(
        button for button in app.button if button.label == "Nueva conversación"
    ).click().run()


class StreamlitFormTests(unittest.TestCase):
    def estimation_body(self, body=None):
        return body or build_estimation_response(PHASES, _request(), "v2").model_dump(mode="json")

    def fake_post(self, url, **kwargs):
        if url.rstrip("/").endswith("/sessions"):
            return _json_response("POST", url, {"session_id": SESSION_ID})
        return _json_response("POST", url, self.estimation_body())

    def fake_get(self, url, **kwargs):
        return _json_response(
            "GET", url, {"session_id": SESSION_ID, "project_metadata": EXTRACTED_METADATA},
        )

    def test_submission_opens_session_and_posts_multipart_estimate(self):
        with patch("httpx.post", side_effect=self.fake_post) as post, patch(
            "httpx.get", side_effect=self.fake_get
        ) as get:
            app = AppTest.from_file(str(APP)).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_input), 0)
            self.assertEqual(len(app.text_area), 1)
            self.assertEqual(len(app.selectbox), 3)
            self.assertTrue(any(button.label == "Nueva conversación" for button in app.button))
            app.text_area[0].set_value(DESCRIPTION)
            app.selectbox[0].select("mobile_app")
            app.selectbox[1].select("detailed")
            app.selectbox[2].select("phases_table")
            app = _click_submit(app)
            self.assertFalse(app.exception)
            self.assertEqual(post.call_count, 2)
            self.assertTrue(post.call_args_list[0].args[0].endswith("/sessions"))
            estimate_call = post.call_args_list[1]
            self.assertTrue(
                estimate_call.args[0].endswith(f"/sessions/{SESSION_ID}/estimate")
            )
            self.assertEqual(estimate_call.kwargs["data"], {
                "transcript": DESCRIPTION, "project_type": "mobile_app",
                "detail_level": "detailed", "output_format": "phases_table",
            })
            get.assert_called_once()
            self.assertTrue(get.call_args.args[0].endswith(f"/sessions/{SESSION_ID}"))
            rendered = build_estimation_response(PHASES, _request(), "v2").text
            self.assertTrue(any(rendered in item.value for item in app.markdown))
            self.assertEqual(app.session_state["project_metadata"], EXTRACTED_METADATA)
            app.run()
            self.assertEqual(post.call_count, 2)
            self.assertTrue(any(rendered in item.value for item in app.markdown))
            self.assertEqual(app.session_state["project_metadata"], EXTRACTED_METADATA)

    def test_new_conversation_opens_session_and_resets_client_state(self):
        session_ids = iter([SESSION_ID, NEW_SESSION_ID])

        def fake_post(url, **kwargs):
            if url.rstrip("/").endswith("/sessions"):
                return _json_response("POST", url, {"session_id": next(session_ids)})
            return _json_response("POST", url, self.estimation_body())

        with patch("httpx.post", side_effect=fake_post) as post, patch(
            "httpx.get", side_effect=self.fake_get
        ):
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(DESCRIPTION)
            app = _click_submit(app)
            self.assertEqual(app.session_state["session_id"], SESSION_ID)
            self.assertIn("estimation_result", app.session_state)
            self.assertEqual(app.session_state["project_metadata"], EXTRACTED_METADATA)

            app = _click_new_conversation(app)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["session_id"], NEW_SESSION_ID)
            self.assertNotIn("estimation_result", app.session_state)
            self.assertEqual(
                app.session_state["project_metadata"],
                {
                    "project_name": None,
                    "assumed_team_size": None,
                    "mentioned_technologies": [],
                    "agreed_scope": None,
                },
            )
            self.assertEqual(post.call_count, 3)
            self.assertTrue(post.call_args_list[-1].args[0].endswith("/sessions"))

    def test_invalid_description_never_calls_http(self):
        with patch("httpx.post") as post, patch("httpx.get") as get:
            app = AppTest.from_file(str(APP)).run()
            for text in ("", "corto", " " * 25):
                app.text_area[0].set_value(text)
                app = _click_submit(app)
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
            post.assert_not_called()
            get.assert_not_called()

    def test_http_errors_and_invalid_responses_are_displayed(self):
        cases = (
            (422, self.estimation_body()),
            (503, self.estimation_body()),
            (404, {"detail": "gone"}),
            (200, {"unexpected": True}),
            httpx.ConnectError("offline"),
            httpx.ReadTimeout("slow"),
        )
        for case in cases:
            with self.subTest(case=case), patch("httpx.post") as post, patch("httpx.get") as get:
                def fake(url, **kwargs):
                    if url.rstrip("/").endswith("/sessions"):
                        return _json_response("POST", url, {"session_id": SESSION_ID})
                    if isinstance(case, Exception):
                        raise case
                    status, body = case
                    return _json_response("POST", url, body, status=status)

                post.side_effect = fake
                get.return_value = _json_response(
                    "GET",
                    f"http://localhost:8000/sessions/{SESSION_ID}",
                    {"session_id": SESSION_ID, "project_metadata": EXTRACTED_METADATA},
                )
                app = AppTest.from_file(str(APP)).run()
                app.text_area[0].set_value(DESCRIPTION)
                app = _click_submit(app)
                self.assertFalse(app.exception)
                self.assertTrue(app.error)

    def test_form_posts_to_real_fastapi_contract_without_llm_network(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.sessions import clear_sessions, get_session

        clear_sessions()
        with TestClient(app) as api, patch(
            "app.routers.estimations.generate_estimation", new_callable=AsyncMock, return_value=LINE_ITEMS
        ) as generate, patch(
            "app.routers.estimations.extract_project_metadata",
            new_callable=AsyncMock,
            return_value=ProjectMetadata(project_name="Inventario", assumed_team_size=3),
        ), patch("httpx.post") as post, patch("httpx.get") as get:
            def proxy_post(url, **kwargs):
                if url.rstrip("/").endswith("/sessions"):
                    return api.post("/sessions")
                return api.post(
                    url[url.find("/sessions/"):],
                    data=kwargs.get("data"),
                    files=kwargs.get("files"),
                )

            def proxy_get(url, **kwargs):
                return api.get(url[url.find("/sessions/"):])

            post.side_effect = proxy_post
            get.side_effect = proxy_get
            app_test = AppTest.from_file(str(APP)).run()
            app_test.text_area[0].set_value(DESCRIPTION)
            app_test.selectbox[0].select("web_saas")
            app_test.selectbox[1].select("summary")
            app_test.selectbox[2].select("line_items")
            app_test = _click_submit(app_test)
            self.assertFalse(app_test.exception)
            self.assertTrue(any("API" in item.value for item in app_test.markdown))
            request = generate.call_args.args[0]
            self.assertEqual(request.project_type.value, "web_saas")
            self.assertEqual(request.detail_level.value, "summary")
            self.assertEqual(request.output_format.value, "line_items")
            session_id = post.call_args_list[1].args[0].rstrip("/").split("/")[-2]
            self.assertEqual(len(get_session(session_id).history.messages), 3)
            self.assertEqual(
                app_test.session_state["project_metadata"]["project_name"],
                "Inventario",
            )
        clear_sessions()

    def test_api_url_is_configurable_without_llm_credentials(self):
        with patch.dict("os.environ", {"ESTIMATION_API_URL": "http://service:9000/"}), patch(
            "httpx.post", side_effect=self.fake_post
        ) as post, patch("httpx.get", side_effect=self.fake_get) as get:
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(DESCRIPTION)
            app = _click_submit(app)
            self.assertFalse(app.exception)
            self.assertEqual(post.call_args_list[0].args[0], "http://service:9000/sessions")
            self.assertEqual(
                post.call_args_list[1].args[0],
                f"http://service:9000/sessions/{SESSION_ID}/estimate",
            )
            self.assertEqual(get.call_args.args[0], f"http://service:9000/sessions/{SESSION_ID}")
