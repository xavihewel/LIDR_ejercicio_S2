"""Extracción local de adjuntos (camino B): solo texto llega al LLM."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS = 5

_TEXT_SUFFIXES = {".txt", ".md"}
_PDF_SUFFIXES = {".pdf"}


class UnsupportedAttachmentError(ValueError):
    """El tipo de fichero no está soportado en el camino B."""


class AttachmentTooLargeError(ValueError):
    """El fichero supera el límite de tamaño aceptado."""


class TooManyAttachmentsError(ValueError):
    """Se enviaron más adjuntos de los permitidos."""


def extract_attachment(filename: str, content_type: str | None, data: bytes) -> str:
    """Devuelve el texto del adjunto. No llama al proveedor LLM."""
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentTooLargeError(
            f"El adjunto supera el límite de {MAX_ATTACHMENT_BYTES} bytes."
        )
    suffix = Path(filename or "").suffix.lower()
    if suffix in _TEXT_SUFFIXES or (content_type or "").startswith("text/"):
        return data.decode("utf-8")
    if suffix in _PDF_SUFFIXES or content_type == "application/pdf":
        return _extract_pdf(data)
    raise UnsupportedAttachmentError(
        f"Tipo de adjunto no soportado: {filename or content_type or 'desconocido'}"
    )


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    parts = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        parts.append(f"--- Page {index} ---\n{text}")
    return "\n\n".join(parts)


def compose_description(
    transcript: str, attachments: list[tuple[str, str]]
) -> str:
    """Concatena el transcript y los textos extraídos con separadores explícitos."""
    if not attachments:
        return transcript
    blocks = [transcript]
    for filename, text in attachments:
        blocks.append(f"--- attachment: {filename} ---\n{text}")
    return "\n\n".join(blocks)


def extract_attachments(
    files: list[tuple[str, str | None, bytes]],
) -> list[tuple[str, str]]:
    """Valida el cupo y extrae todos los adjuntos en orden."""
    if len(files) > MAX_ATTACHMENTS:
        raise TooManyAttachmentsError(
            f"Como máximo se admiten {MAX_ATTACHMENTS} adjuntos."
        )
    extracted: list[tuple[str, str]] = []
    for filename, content_type, data in files:
        name = Path(filename or "attachment").name
        extracted.append((name, extract_attachment(name, content_type, data)))
    return extracted
