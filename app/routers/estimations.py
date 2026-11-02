"""Endpoints HTTP para generar estimaciones de software."""
from fastapi import APIRouter, HTTPException
from openai import APIError, APITimeoutError

from app.schemas import EstimationRequest, EstimationResponse
from app.config import get_settings
from app.services.llm_service import generate_estimation

router = APIRouter(tags=["estimations"])


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest) -> EstimationResponse:
    """Genera una estimación a partir de la transcripción de una reunión."""
    try:
        settings = get_settings()
        estimation = await generate_estimation(request)
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

    return EstimationResponse(
        estimation=estimation,
        model=settings.llm_model,
        provider=settings.llm_provider,
    )
