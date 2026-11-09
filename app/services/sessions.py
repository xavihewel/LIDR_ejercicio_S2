"""Estado conversacional en memoria del proceso.

Sin base de datos y sin Redis: en esta fase la sesión solo sirve para iterar
prompt y metadata entre turnos del mismo proceso. Se acepta perder el estado
al reiniciar porque aún no hay multi-instancia ni recuperación de
conversaciones. Redis queda reservado a la caché exact-match del LLM.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.schemas import EstimationRequest

MAX_TURNS = 6


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("El texto no puede estar vacío.")
    return value


class ConversationHistory:
    """Lista de mensajes con ventana deslizante por turnos user+assistant."""

    def __init__(self, max_turns: int = MAX_TURNS):
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

    def to_messages_list(
        self,
        *,
        request: EstimationRequest,
        project_metadata: ProjectMetadata,
    ) -> list[dict[str, str]]:
        """Mensajes listos para el LLM: system regenerado + turnos de la ventana."""
        from app.prompts.loader import render_estimation_prompt

        system, _ = render_estimation_prompt(request, project_metadata=project_metadata)
        turns = [
            message.copy()
            for message in self._messages
            if message["role"] != "system"
        ]
        return [{"role": "system", "content": system}, *turns]

    def messages_for_llm(
        self,
        *,
        request: EstimationRequest,
        project_metadata: ProjectMetadata,
        user_content: str,
    ) -> list[dict[str, str]]:
        """Historial efectivo a enviar: ventana + turno user actual, sin superar max_turns."""
        messages = self.to_messages_list(
            request=request, project_metadata=project_metadata,
        )
        messages.append({"role": "user", "content": user_content})
        while self._user_count(messages) > self.max_turns:
            if not self._drop_oldest_turn_from(messages):
                break
        return messages

    @staticmethod
    def _user_count(messages: list[dict[str, str]]) -> int:
        return sum(1 for message in messages if message["role"] == "user")

    @staticmethod
    def _drop_oldest_turn_from(messages: list[dict[str, str]]) -> bool:
        start = 1 if messages and messages[0]["role"] == "system" else 0
        if start >= len(messages) or messages[start]["role"] != "user":
            return False
        del messages[start]
        if start < len(messages) and messages[start]["role"] == "assistant":
            del messages[start]
        return True

    def _replace_system(self, content: str) -> None:
        system = {"role": "system", "content": content}
        for index, message in enumerate(self._messages):
            if message["role"] == "system":
                self._messages[index] = system
                return
        self._messages.insert(0, system)

    def _trim_to_window(self) -> None:
        while self._turn_count() > self.max_turns:
            if not self._drop_oldest_turn():
                break

    def _drop_oldest_turn(self) -> bool:
        """Elimina el par user(+assistant) más antiguo. Preserva el system."""
        start = 1 if self._messages and self._messages[0]["role"] == "system" else 0
        if start >= len(self._messages):
            return False
        del self._messages[start]
        if start < len(self._messages) and self._messages[start]["role"] == "assistant":
            del self._messages[start]
        return True

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

    @property
    def is_empty(self) -> bool:
        """True en la primera llamada de sesión, antes de acordar hechos."""
        return (
            self.project_name is None
            and self.assumed_team_size is None
            and not self.mentioned_technologies
            and self.agreed_scope is None
        )

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

    def __init__(self, session_id: str, *, max_turns: int = MAX_TURNS):
        self.session_id = session_id
        self.history = ConversationHistory(max_turns=max_turns)
        self.metadata = ProjectMetadata()

    def to_messages_list(self, request: EstimationRequest) -> list[dict[str, str]]:
        """System regenerado con la metadata actual + turnos retenidos."""
        return self.history.to_messages_list(
            request=request, project_metadata=self.metadata,
        )

    def messages_for_llm(self, request: EstimationRequest, user_content: str) -> list[dict[str, str]]:
        """Payload de chat listo para el LLM, acotado a la ventana de la sesión."""
        return self.history.messages_for_llm(
            request=request,
            project_metadata=self.metadata,
            user_content=user_content,
        )


_SESSIONS: dict[str, Session] = {}


def create_session(*, max_turns: int = MAX_TURNS) -> Session:
    """Abre una sesión nueva con un UUID v4. El cliente reenvía el id después."""
    return get_or_create_session(str(uuid4()), max_turns=max_turns)


def get_or_create_session(session_id: str, *, max_turns: int = MAX_TURNS) -> Session:
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
