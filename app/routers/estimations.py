"""Endpoints HTTP para generar estimaciones de software."""
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from openai import APIError, APITimeoutError

from app.schemas import EstimationRequest, EstimationResponse
from app.prompts.loader import DEFAULT_PROMPT_VERSION, render_estimation_prompt
from app.services.llm_service import generate_estimation
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


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(
    request: EstimationRequest,
    x_session_id: Annotated[str | None, Header()] = None,
) -> EstimationResponse:
    """Genera una estimación estructurada a partir del formulario.

    El cliente puede reenviar X-Session-ID (de POST /sessions) para acumular
    turnos en la memoria del proceso entre páginas o peticiones.
    """
    session = _resolve_session(x_session_id)
    try:
        system, user = render_estimation_prompt(request)
        estimation = await generate_estimation(request, prompt=(system, user))
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
    return response
