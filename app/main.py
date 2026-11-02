"""Punto de entrada HTTP."""
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from structlog.contextvars import bound_contextvars

from app.observability import configure_logging
from app.routers.estimations import router

configure_logging()
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="Estimador CAG",
    description=(
        "API de estimación de proyectos de software a partir de transcripciones "
        "de reuniones. Utiliza un LLM con ejemplos previos incluidos como "
        "contexto (CAG) para generar un desglose de tareas, horas, equipo "
        "recomendado y duración estimada."
    ),
)
app.include_router(router, prefix="/api/v1")


@app.middleware("http")
async def observe_request(request: Request, call_next):
    request_id = uuid4().hex
    started = perf_counter()
    with bound_contextvars(request_id=request_id):
        fields = {"request_id": request_id, "method": request.method}
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "http_request_failed", **fields, error_type=type(exc).__name__,
                duration_seconds=perf_counter() - started,
            )
            raise
        route = request.scope.get("route")
        logger.info(
            "http_request_completed", **fields,
            route=getattr(route, "path", "unmatched"), status_code=response.status_code,
            duration_seconds=perf_counter() - started,
        )
        response.headers["X-Request-ID"] = request_id
        return response


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Indica que la API está activa; no consulta al proveedor LLM."""
    return {"status": "ok"}


def main() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
