"""Endpoints HTTP para abrir y localizar sesiones en memoria."""
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.services.sessions import ProjectMetadata, create_session, get_session

router = APIRouter(tags=["sessions"])


class SessionCreated(BaseModel):
    session_id: str = Field(min_length=1)


class SessionState(BaseModel):
    session_id: str = Field(min_length=1)
    project_metadata: ProjectMetadata


@router.post("/sessions", response_model=SessionCreated)
async def open_session() -> SessionCreated:
    """Crea una sesión en memoria. El cliente reenvía session_id en peticiones posteriores."""
    return SessionCreated(
        session_id=create_session(max_turns=get_settings().session_max_turns).session_id
    )


@router.get("/sessions/{session_id}", response_model=SessionState)
async def read_session(session_id: str) -> SessionState:
    """Devuelve el project_metadata actual (memoria), distinto del historial de turnos."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail="La sesión no existe o ha expirado."
        )
    return SessionState(session_id=session.session_id, project_metadata=session.metadata)
