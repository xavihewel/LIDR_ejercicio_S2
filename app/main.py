"""Punto de entrada HTTP."""
from fastapi import FastAPI
from app.routers.estimations import router

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


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Indica que la API está activa; no consulta al proveedor LLM."""
    return {"status": "ok"}


def main() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
