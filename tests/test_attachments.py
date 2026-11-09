"""Extracción local de adjuntos (camino B), sin red ni LLM."""
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter

from app.services.attachments import (
    AttachmentTooLargeError,
    UnsupportedAttachmentError,
    compose_description,
    extract_attachment,
)


def blank_pdf_bytes() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


class ExtractAttachmentTests(unittest.TestCase):
    def test_extracts_plain_text_and_markdown(self):
        for name, content_type, payload in (
            ("notes.txt", "text/plain", "Requisitos del MVP"),
            ("scope.md", "text/markdown", "# Alcance\nLogin y chat"),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    extract_attachment(name, content_type, payload.encode("utf-8")),
                    payload,
                )

    def test_pdf_emits_page_markers(self):
        text = extract_attachment("spec.pdf", "application/pdf", blank_pdf_bytes())
        self.assertIn("--- Page 1 ---", text)

    def test_pdf_includes_extracted_page_text(self):
        page = MagicMock()
        page.extract_text.return_value = "Diagrama de módulos"
        reader = MagicMock()
        reader.pages = [page]
        with patch("app.services.attachments.PdfReader", return_value=reader):
            text = extract_attachment("spec.pdf", "application/pdf", b"%PDF")
        self.assertEqual(text, "--- Page 1 ---\nDiagrama de módulos")

    def test_rejects_unsupported_types_and_oversize_files(self):
        with self.assertRaises(UnsupportedAttachmentError):
            extract_attachment("virus.exe", "application/octet-stream", b"MZ")
        with self.assertRaises(AttachmentTooLargeError):
            extract_attachment("huge.txt", "text/plain", b"x" * (5 * 1024 * 1024 + 1))


class ComposeDescriptionTests(unittest.TestCase):
    def test_returns_transcript_when_there_are_no_attachments(self):
        transcript = "Aplicación móvil con login y chat."
        self.assertEqual(compose_description(transcript, []), transcript)

    def test_appends_attachment_blocks_with_clear_separators(self):
        composed = compose_description(
            "Transcripción de la reunión.",
            [("spec.pdf", "Página con requisitos"), ("notes.txt", "Notas del cliente")],
        )
        self.assertEqual(
            composed,
            "Transcripción de la reunión.\n\n"
            "--- attachment: spec.pdf ---\n"
            "Página con requisitos\n\n"
            "--- attachment: notes.txt ---\n"
            "Notas del cliente",
        )
