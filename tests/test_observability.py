"""Logs operativos sin contenido de las peticiones ni errores sensibles."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import structlog
from structlog.testing import capture_logs
from fastapi.testclient import TestClient

from app.observability import configure_logging
from app.main import app
from app.config import Settings
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.llm_service import generate_estimation, stream_estimation

PHASES = json.dumps({
    "phases": [{"phase": "Entrega", "duration_weeks": 2, "cost_eur": 0, "confidence_pct": 50}],
    "total_duration_weeks": 2,
})


def sample(description):
    return EstimationRequest(
        description=description, project_type=ProjectType.SOFTWARE,
        detail_level=DetailLevel.DETAILED, output_format=OutputFormat.PHASES_TABLE,
    )


class LoggingTests(unittest.TestCase):
    def test_json_output_and_level_filtering(self):
        output = io.StringIO()
        previous = structlog.get_config().copy()
        self.addCleanup(lambda: structlog.configure(**previous))
        configure_logging("WARNING", output=output)
        structlog.get_logger().info("hidden")
        structlog.get_logger().warning("visible", count=2)
        event = json.loads(output.getvalue())
        self.assertEqual(event["event"], "visible")
        self.assertEqual(event["level"], "warning")
        self.assertIn("timestamp", event)

    def test_http_requests_have_distinct_ids_and_structured_status(self):
        with capture_logs() as events, TestClient(app) as client:
            first = client.get("/health")
            second = client.get("/health")
        self.assertNotEqual(first.headers["X-Request-ID"], second.headers["X-Request-ID"])
        records = [e for e in events if e["event"] == "http_request_completed"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["request_id"], first.headers["X-Request-ID"])
        self.assertEqual(records[0]["status_code"], 200)
        self.assertGreaterEqual(records[0]["duration_seconds"], 0)


class EstimationLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_failures_in_both_modes_log_type_without_sensitive_text(self):
        settings = Settings(_env_file=None, openai_api_key="secret-key", cache_enabled=False)
        with patch("app.services.llm_service.get_settings", return_value=settings), patch(
            "app.services.llm_service.complete", new_callable=AsyncMock,
            side_effect=RuntimeError("private transcript about a mobile app secret-key"),
        ), capture_logs() as events:
            with self.assertRaises(RuntimeError):
                await generate_estimation(sample("private transcript about a mobile app"))
            with self.assertRaises(RuntimeError):
                _ = [part async for part in stream_estimation(sample("private transcript about a mobile app"))]
        failures = [e for e in events if e["event"] == "estimation_failed"]
        self.assertEqual(len(failures), 2)
        for event in failures:
            self.assertEqual(event["error_type"], "RuntimeError")
            self.assertEqual(event["provider"], "openai")
            self.assertGreaterEqual(event["duration_seconds"], 0)
        self.assertNotIn("private transcript about a mobile app", json.dumps(events))
        self.assertNotIn("secret-key", json.dumps(events))

    async def test_success_logs_usage_and_cache_hit_without_counting_a_new_call(self):
        from app.services.llm_cache import CachedEstimation
        settings = Settings(_env_file=None, openai_api_key="test", cache_enabled=True)
        response = SimpleNamespace(
            model="resolved", usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=PHASES))],
        )
        with patch("app.services.llm_service.get_settings", return_value=settings), patch(
            "app.services.llm_service.LLMCache"
        ) as factory, patch("app.services.llm_service.complete", new_callable=AsyncMock, return_value=response), capture_logs() as events:
            cache = factory.return_value
            cache.get = AsyncMock(return_value=None)
            cache.set = AsyncMock()
            request = sample("Input describing a mobile application")
            await generate_estimation(request)
            cache.get.return_value = CachedEstimation(content=PHASES, model="resolved", tokens_in=12, tokens_out=3)
            _ = [part async for part in stream_estimation(request)]
        completed = [e for e in events if e["event"] == "estimation_completed"]
        self.assertEqual([e["cache_hit"] for e in completed], [False, True])
        for event in completed:
            self.assertEqual(event["input_tokens"], 12)
            self.assertEqual(event["output_tokens"], 3)
            self.assertEqual(event["model"], "resolved")

    async def test_interrupted_stream_logs_cancellation_instead_of_success(self):
        settings = Settings(_env_file=None, openai_api_key="test", cache_enabled=False)
        upstream = AsyncMock()
        upstream.__aiter__.return_value = [SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="Partial"), finish_reason=None
        )])]
        with patch("app.services.llm_service.get_settings", return_value=settings), patch(
            "app.services.llm_service.complete", new_callable=AsyncMock, return_value=upstream
        ), capture_logs() as events:
            result = stream_estimation(sample("Input describing a mobile application"))
            await anext(result)
            await result.aclose()
        self.assertEqual(
            [e["event"] for e in events if e["event"].startswith("estimation_")],
            ["estimation_cancelled"],
        )
        upstream.aclose.assert_awaited_once()
