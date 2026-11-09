"""Sesiones en memoria: historia con ventana y metadata del proyecto."""
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.sessions import (
    MAX_TURNS,
    ConversationHistory,
    ProjectMetadata,
    Session,
    clear_sessions,
    get_or_create_session,
    get_session,
)


def _request() -> EstimationRequest:
    return EstimationRequest(
        description="Aplicación móvil con login, chat y notificaciones push.",
        project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED,
        output_format=OutputFormat.PHASES_TABLE,
    )


class ConversationHistoryTests(unittest.TestCase):
    def test_default_max_turns_is_six(self):
        self.assertEqual(MAX_TURNS, 6)
        self.assertEqual(ConversationHistory().max_turns, 6)

    def test_keeps_system_prompt_when_sliding_window_discards_oldest_pairs(self):
        history = ConversationHistory(max_turns=2)
        history.append("system", "Reglas del estimador")
        history.append("user", "Primera pregunta")
        history.append("assistant", "Primera respuesta")
        history.append("user", "Segunda pregunta")
        history.append("assistant", "Segunda respuesta")
        history.append("user", "Tercera pregunta")
        history.append("assistant", "Tercera respuesta")

        messages = history.messages
        self.assertEqual(messages[0], {"role": "system", "content": "Reglas del estimador"})
        self.assertEqual([message["content"] for message in messages[1:]], [
            "Segunda pregunta", "Segunda respuesta",
            "Tercera pregunta", "Tercera respuesta",
        ])

    def test_discards_complete_user_assistant_pairs_not_single_messages(self):
        history = ConversationHistory(max_turns=1)
        history.append("user", "u1")
        history.append("assistant", "a1")
        history.append("user", "u2")
        history.append("assistant", "a2")
        self.assertEqual(history.messages, [
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ])

    def test_replacing_system_keeps_a_single_system_message(self):
        history = ConversationHistory(max_turns=3)
        history.append("system", "Primera versión")
        history.append("user", "Hola")
        history.append("system", "Segunda versión")
        self.assertEqual(history.messages, [
            {"role": "system", "content": "Segunda versión"},
            {"role": "user", "content": "Hola"},
        ])

    def test_messages_returns_a_copy(self):
        history = ConversationHistory(max_turns=2)
        history.append("user", "Hola")
        history.messages.append({"role": "user", "content": "Mutación externa"})
        self.assertEqual(history.messages, [{"role": "user", "content": "Hola"}])

    def test_to_messages_list_regenerates_system_from_current_metadata(self):
        history = ConversationHistory(max_turns=6)
        history.append("system", "System obsoleto")
        history.append("user", "Necesito una estimación")
        history.append("assistant", '{"phases":[]}')
        metadata = ProjectMetadata(
            project_name="Reservas",
            assumed_team_size=2,
            mentioned_technologies=["FastAPI"],
            agreed_scope="MVP de citas",
        )
        with patch(
            "app.prompts.loader.render_estimation_prompt",
            return_value=("System regenerado con metadata", "ignored"),
        ) as render:
            messages = history.to_messages_list(request=_request(), project_metadata=metadata)

        render.assert_called_once_with(_request(), project_metadata=metadata)
        self.assertEqual(messages[0], {"role": "system", "content": "System regenerado con metadata"})
        self.assertEqual(messages[1:], [
            {"role": "user", "content": "Necesito una estimación"},
            {"role": "assistant", "content": '{"phases":[]}'},
        ])
        self.assertEqual(history.messages[0]["content"], "System obsoleto")

    def test_messages_for_llm_caps_outbound_history_to_max_turns(self):
        history = ConversationHistory(max_turns=2)
        for index in range(2):
            history.append("user", f"user-{index}")
            history.append("assistant", f"assistant-{index}")
        with patch(
            "app.prompts.loader.render_estimation_prompt",
            return_value=("System actual", "ignored"),
        ):
            messages = history.messages_for_llm(
                request=_request(),
                project_metadata=ProjectMetadata(),
                user_content="user-nuevo",
            )
        users = [message["content"] for message in messages if message["role"] == "user"]
        self.assertEqual(users, ["user-1", "user-nuevo"])
        self.assertEqual(messages[0]["content"], "System actual")


class ProjectMetadataTests(unittest.TestCase):
    def test_accepts_the_documented_fields(self):
        metadata = ProjectMetadata(
            project_name="Reservas",
            assumed_team_size=3,
            mentioned_technologies=["Python", "Redis"],
            agreed_scope="MVP con login y calendario",
        )
        self.assertEqual(metadata.project_name, "Reservas")
        self.assertEqual(metadata.assumed_team_size, 3)
        self.assertEqual(metadata.mentioned_technologies, ["Python", "Redis"])
        self.assertEqual(metadata.agreed_scope, "MVP con login y calendario")

    def test_defaults_allow_an_empty_session_start(self):
        metadata = ProjectMetadata()
        self.assertIsNone(metadata.project_name)
        self.assertIsNone(metadata.assumed_team_size)
        self.assertEqual(metadata.mentioned_technologies, [])
        self.assertIsNone(metadata.agreed_scope)
        self.assertTrue(metadata.is_empty)
        self.assertFalse(ProjectMetadata(project_name="Reservas").is_empty)

    def test_rejects_blank_text_and_non_positive_team_size(self):
        for kwargs in (
            {"project_name": "   "},
            {"agreed_scope": "\n"},
            {"assumed_team_size": 0},
            {"assumed_team_size": -1},
            {"mentioned_technologies": ["  "]},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    ProjectMetadata(**kwargs)


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        clear_sessions()

    def tearDown(self):
        clear_sessions()

    def test_session_holds_history_and_metadata(self):
        session = Session(session_id="s1")
        self.assertEqual(session.session_id, "s1")
        self.assertIsInstance(session.history, ConversationHistory)
        self.assertIsInstance(session.metadata, ProjectMetadata)
        self.assertEqual(session.history.max_turns, MAX_TURNS)

    def test_session_to_messages_list_uses_current_metadata(self):
        session = Session(session_id="s1")
        session.metadata = ProjectMetadata(project_name="Inventario")
        session.history.append("user", "Estima el inventario")
        session.history.append("assistant", "{}")
        with patch(
            "app.prompts.loader.render_estimation_prompt",
            return_value=("System de sesión", "ignored"),
        ) as render:
            messages = session.to_messages_list(_request())
        render.assert_called_once_with(_request(), project_metadata=session.metadata)
        self.assertEqual(messages[0]["content"], "System de sesión")
        self.assertEqual(len(messages), 3)

    def test_get_or_create_reuses_the_same_instance_by_session_id(self):
        first = get_or_create_session("abc")
        first.metadata.project_name = "Inventario"
        first.history.append("user", "Necesito una estimación")
        second = get_or_create_session("abc")
        other = get_or_create_session("xyz")

        self.assertIs(first, second)
        self.assertIsNot(first, other)
        self.assertEqual(second.metadata.project_name, "Inventario")
        self.assertEqual(second.history.messages[0]["content"], "Necesito una estimación")
        self.assertIs(get_session("abc"), first)
        self.assertIsNone(get_session("missing"))

    def test_clear_sessions_drops_in_memory_state(self):
        get_or_create_session("abc")
        clear_sessions()
        self.assertIsNone(get_session("abc"))
