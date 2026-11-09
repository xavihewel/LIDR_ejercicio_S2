"""Integración HTTP con pytest + httpx.AsyncClient (sin proveedor LLM real)."""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.main import app
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.sessions import MAX_TURNS, ProjectMetadata, clear_sessions, get_session

TRANSCRIPT = "Aplicación móvil con login, chat y notificaciones push."
PDF_TOKEN = "TOKEN-PDF-12-WEEKS"

FORM = {
    "transcript": TRANSCRIPT,
    "project_type": "mobile_app",
    "detail_level": "detailed",
    "output_format": "phases_table",
}


def _phases(*, total_weeks: int, phase: str = "Desarrollo") -> str:
    return json.dumps(
        {
            "phases": [
                {
                    "phase": phase,
                    "duration_weeks": total_weeks,
                    "cost_eur": total_weeks * 1000,
                    "confidence_pct": 70,
                }
            ],
            "total_duration_weeks": total_weeks,
        },
        ensure_ascii=False,
    )


def _pdf_with_text(text: str) -> bytes:
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("latin-1"))
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    page[NameObject("/Contents")] = stream
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _user_turn_count(messages: list[dict[str, str]]) -> int:
    return sum(1 for message in messages if message["role"] == "user")


@pytest.fixture
async def client():
    clear_sessions()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    clear_sessions()


@pytest.mark.asyncio
async def test_session_links_two_requests_and_updates_project_metadata(client: AsyncClient):
    metadata_turns = [
        ProjectMetadata(project_name="App móvil", assumed_team_size=2),
        ProjectMetadata(
            project_name="App móvil",
            assumed_team_size=4,
            mentioned_technologies=["Flutter"],
            agreed_scope="Login, chat y push",
        ),
    ]
    with patch(
        "app.routers.estimations.generate_estimation",
        new_callable=AsyncMock,
        return_value=_phases(total_weeks=6),
    ) as generate, patch(
        "app.routers.estimations.extract_project_metadata",
        new_callable=AsyncMock,
        side_effect=metadata_turns,
    ):
        created = await client.post("/sessions")
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        first = await client.post(f"/sessions/{session_id}/estimate", data=FORM)
        assert first.status_code == 200
        state_after_first = await client.get(f"/sessions/{session_id}")
        assert state_after_first.status_code == 200
        assert state_after_first.json()["project_metadata"] == metadata_turns[0].model_dump()

        second = await client.post(
            f"/sessions/{session_id}/estimate",
            data=FORM | {"transcript": TRANSCRIPT + " Equipo de cuatro personas con Flutter."},
        )
        assert second.status_code == 200
        state_after_second = await client.get(f"/sessions/{session_id}")
        assert state_after_second.json()["project_metadata"] == metadata_turns[1].model_dump()

        second_system = generate.await_args_list[1].kwargs["messages"][0]["content"]
        assert "<project_name>App móvil</project_name>" in second_system
        assert "<assumed_team_size>2</assumed_team_size>" in second_system
        assert get_session(session_id).metadata == metadata_turns[1]


@pytest.mark.asyncio
async def test_pdf_attachment_changes_a_concrete_estimation_field(client: AsyncClient):
    async def generate_from_prompt(request, *, prompt=None, messages=None):
        payload = messages if messages is not None else [
            {"role": "system", "content": prompt[0]},
            {"role": "user", "content": prompt[1]},
        ]
        user = payload[-1]["content"]
        if PDF_TOKEN in user:
            return _phases(total_weeks=12, phase="Integración PDF")
        return _phases(total_weeks=4, phase="MVP sin adjunto")

    with patch(
        "app.routers.estimations.generate_estimation",
        new_callable=AsyncMock,
        side_effect=generate_from_prompt,
    ), patch(
        "app.routers.estimations.extract_project_metadata",
        new_callable=AsyncMock,
        return_value=ProjectMetadata(),
    ):
        session_id = (await client.post("/sessions")).json()["session_id"]
        without = await client.post(f"/sessions/{session_id}/estimate", data=FORM)
        assert without.status_code == 200
        assert without.json()["phases_table"]["total_duration_weeks"] == 4

        other_session = (await client.post("/sessions")).json()["session_id"]
        with_pdf = await client.post(
            f"/sessions/{other_session}/estimate",
            data=FORM,
            files=[
                (
                    "attachments",
                    ("spec.pdf", _pdf_with_text(PDF_TOKEN), "application/pdf"),
                )
            ],
        )
        assert with_pdf.status_code == 200
        assert with_pdf.json()["phases_table"]["total_duration_weeks"] == 12
        assert with_pdf.json()["phases_table"]["phases"][0]["phase"] == "Integración PDF"
        assert without.json()["phases_table"]["total_duration_weeks"] != (
            with_pdf.json()["phases_table"]["total_duration_weeks"]
        )


@pytest.mark.asyncio
async def test_eight_turns_never_send_more_than_max_turns_to_the_llm(client: AsyncClient):
    captured: list[list[dict[str, str]]] = []

    async def capture_messages(request, *, prompt=None, messages=None):
        assert messages is not None
        captured.append([message.copy() for message in messages])
        return _phases(total_weeks=3, phase=f"Turno {len(captured)}")

    with patch(
        "app.routers.estimations.generate_estimation",
        new_callable=AsyncMock,
        side_effect=capture_messages,
    ), patch(
        "app.routers.estimations.extract_project_metadata",
        new_callable=AsyncMock,
        return_value=ProjectMetadata(project_name="Ventana"),
    ):
        session_id = (await client.post("/sessions")).json()["session_id"]
        request = EstimationRequest(
            description=TRANSCRIPT,
            project_type=ProjectType.MOBILE_APP,
            detail_level=DetailLevel.DETAILED,
            output_format=OutputFormat.PHASES_TABLE,
        )
        for index in range(8):
            response = await client.post(
                f"/sessions/{session_id}/estimate",
                data=FORM | {"transcript": f"{TRANSCRIPT} Turno {index + 1}."},
            )
            assert response.status_code == 200
            assert _user_turn_count(captured[-1]) <= MAX_TURNS
            assert len(captured[-1]) <= 1 + (2 * MAX_TURNS)

        assert len(captured) == 8
        assert _user_turn_count(captured[-1]) == MAX_TURNS
        assert "Turno 1." not in captured[-1][-1]["content"]
        assert "Turno 8." in captured[-1][-1]["content"]
        stored_users = _user_turn_count(get_session(session_id).to_messages_list(request))
        assert stored_users == MAX_TURNS
