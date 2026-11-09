"""Endpoints HTTP para generar estimaciones de software."""
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from openai import APIError, APITimeoutError
from pydantic import ValidationError

from app.schemas import (
    DetailLevel,
    EstimationRequest,
    EstimationResponse,
    OutputFormat,
    ProjectType,
)
from app.prompts.loader import DEFAULT_PROMPT_VERSION, render_estimation_prompt
from app.services.attachments import (
    AttachmentTooLargeError,
    TooManyAttachmentsError,
    UnsupportedAttachmentError,
    compose_description,
    extract_attachments,
)
from app.services.llm_service import generate_estimation
from app.services.metadata_extractor import extract_project_metadata
from app.services.output_guardrails import build_estimation_response
from app.services.sessions import Session, get_session

router = APIRouter(tags=["estimations"])


def _resolve_session(session_id: str | None) -> Session | None:
    """Si el cliente envía X-Session-ID, la sesión debe existir en este proceso."""
    if session_id is None:
        return None
    session = get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail="La sesión no existe o ha expirado."
        )
    return session


def _require_session(session_id: str) -> Session:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail="La sesión no existe o ha expirado."
        )
    return session


async def _execute_estimation(
    request: EstimationRequest,
    session: Session | None = None,
    *,
    description: str | None = None,
) -> EstimationResponse:
    try:
        system, user = render_estimation_prompt(
            request,
            description=description,
            project_metadata=None if session is None else session.metadata,
        )
        if session is None:
            estimation = await generate_estimation(request, prompt=(system, user))
        else:
            estimation = await generate_estimation(
                request,
                messages=session.messages_for_llm(request, user),
            )
        response = build_estimation_response(estimation, request, DEFAULT_PROMPT_VERSION)
    except APITimeoutError as exc:
        raise HTTPException(
            status_code=504, detail="El proveedor LLM no respondió a tiempo."
        ) from exc
    except (APIError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502, detail="No se pudo obtener una estimación del proveedor LLM."
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=503, detail="El servicio de estimaciones no está configurado correctamente."
        ) from exc
    if session is not None:
        session.history.append("system", system)
        session.history.append("user", user)
        session.history.append("assistant", estimation)
        session.metadata = await extract_project_metadata(
            description=description if description is not None else request.description,
            estimation=estimation,
            current=session.metadata,
        )
    return response


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(
    request: EstimationRequest,
    x_session_id: Annotated[str | None, Header()] = None,
) -> EstimationResponse:
    """Genera una estimación estructurada a partir del formulario JSON.

    El cliente puede reenviar X-Session-ID (de POST /sessions) para acumular
    turnos en la memoria del proceso entre páginas o peticiones.
    """
    return await _execute_estimation(request, _resolve_session(x_session_id))


@router.post("/sessions/{session_id}/estimate", response_model=EstimationResponse)
async def estimate_with_attachments(
    session_id: str,
    transcript: Annotated[str, Form()],
    project_type: Annotated[ProjectType, Form()],
    detail_level: Annotated[DetailLevel, Form()],
    output_format: Annotated[OutputFormat, Form()],
    attachments: Annotated[list[UploadFile] | None, File()] = None,
) -> EstimationResponse:
    """Estimación con transcript y adjuntos opcionales (camino B: texto extraído localmente)."""
    session = _require_session(session_id)
    try:
        request = EstimationRequest(
            description=transcript,
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    files: list[tuple[str, str | None, bytes]] = []
    for upload in attachments or []:
        files.append((upload.filename or "attachment", upload.content_type, await upload.read()))
    try:
        extracted = extract_attachments(files)
    except (UnsupportedAttachmentError, AttachmentTooLargeError, TooManyAttachmentsError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    composed = compose_description(transcript, extracted)
    return await _execute_estimation(request, session, description=composed)
