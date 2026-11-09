"""Endpoints HTTP para abrir y localizar sesiones en memoria."""
from pydantic import BaseModel, Field

from fastapi import APIRouter

from app.services.sessions import create_session

router = APIRouter(tags=["sessions"])


class SessionCreated(BaseModel):
    session_id: str = Field(min_length=1)


@router.post("/sessions", response_model=SessionCreated)
async def open_session() -> SessionCreated:
    """Crea una sesión en memoria. El cliente reenvía session_id en peticiones posteriores."""
    return SessionCreated(session_id=create_session().session_id)
