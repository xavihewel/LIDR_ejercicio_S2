"""Sesiones en memoria: historia con ventana y metadata del proyecto."""
import unittest

from pydantic import ValidationError

from app.services.sessions import (
    ConversationHistory,
    ProjectMetadata,
    Session,
    clear_sessions,
    get_or_create_session,
    get_session,
)


class ConversationHistoryTests(unittest.TestCase):
    def test_keeps_system_prompt_when_sliding_window_discards_old_turns(self):
        history = ConversationHistory(max_turns=2)
        history.append("system", "Reglas del estimador")
        history.append("user", "Primera pregunta")
        history.append("assistant", "Primera respuesta")
        history.append("user", "Segunda pregunta")
        history.append("assistant", "Segunda respuesta")
        history.append("user", "Tercera pregunta")

        messages = history.messages
        self.assertEqual(messages[0], {"role": "system", "content": "Reglas del estimador"})
        self.assertEqual([message["content"] for message in messages[1:]], [
            "Segunda pregunta", "Segunda respuesta", "Tercera pregunta",
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
