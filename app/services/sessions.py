"""Estado conversacional en memoria del proceso.

Sin base de datos y sin Redis: en esta fase la sesión solo sirve para iterar
prompt y metadata entre turnos del mismo proceso. Se acepta perder el estado
al reiniciar porque aún no hay multi-instancia ni recuperación de
conversaciones. Redis queda reservado a la caché exact-match del LLM.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("El texto no puede estar vacío.")
    return value


class ConversationHistory:
    """Lista de mensajes con ventana deslizante por turnos."""

    def __init__(self, max_turns: int = 10):
        if max_turns < 1:
            raise ValueError("max_turns debe ser al menos 1.")
        self.max_turns = max_turns
        self._messages: list[dict[str, str]] = []

    @property
    def messages(self) -> list[dict[str, str]]:
        return [message.copy() for message in self._messages]

    def append(self, role: str, content: str) -> None:
        if role == "system":
            self._replace_system(content)
            return
        self._messages.append({"role": role, "content": content})
        self._trim_to_window()

    def _replace_system(self, content: str) -> None:
        system = {"role": "system", "content": content}
        for index, message in enumerate(self._messages):
            if message["role"] == "system":
                self._messages[index] = system
                return
        self._messages.insert(0, system)

    def _trim_to_window(self) -> None:
        while self._turn_count() > self.max_turns:
            for index, message in enumerate(self._messages):
                if message["role"] != "system":
                    del self._messages[index]
                    break

    def _turn_count(self) -> int:
        """Cuenta pares user/assistant; un user pendiente cuenta como turno."""
        turns = 0
        pending_user = False
        for message in self._messages:
            if message["role"] == "system":
                continue
            if message["role"] == "user":
                turns += 1
                pending_user = True
            elif message["role"] == "assistant" and pending_user:
                pending_user = False
            elif message["role"] == "assistant":
                turns += 1
        return turns


class ProjectMetadata(BaseModel):
    """Hechos acordados del proyecto durante la sesión."""

    project_name: str | None = None
    assumed_team_size: int | None = Field(default=None, gt=0)
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: str | None = None

    @field_validator("project_name", "agreed_scope")
    @classmethod
    def text_fields_are_nonblank(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value)

    @field_validator("mentioned_technologies")
    @classmethod
    def technologies_are_nonblank(cls, values: list[str]) -> list[str]:
        return [_nonblank(value) for value in values]


class Session:
    """Unidad de estado indexada por session_id."""

    def __init__(self, session_id: str, *, max_turns: int = 10):
        self.session_id = session_id
        self.history = ConversationHistory(max_turns=max_turns)
        self.metadata = ProjectMetadata()


_SESSIONS: dict[str, Session] = {}


def create_session(*, max_turns: int = 10) -> Session:
    """Abre una sesión nueva con un UUID v4. El cliente reenvía el id después."""
    return get_or_create_session(str(uuid4()), max_turns=max_turns)


def get_or_create_session(session_id: str, *, max_turns: int = 10) -> Session:
    """Devuelve la sesión existente o crea una nueva en el proceso."""
    session = _SESSIONS.get(session_id)
    if session is None:
        session = Session(session_id, max_turns=max_turns)
        _SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> Session | None:
    return _SESSIONS.get(session_id)


def clear_sessions() -> None:
    """Vacía el almacén en memoria. Pensado para tests y reinicios locales."""
    _SESSIONS.clear()
