"""Actualiza ProjectMetadata con una segunda llamada al LLM tras cada estimación."""

from __future__ import annotations

import json
import re

import structlog
from openai import APIError
from pydantic import ValidationError

from app.config import get_settings
from app.services.llm_provider import complete
from app.services.sessions import ProjectMetadata

logger = structlog.get_logger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_SYSTEM = """\
You extract durable project facts for a software estimation session.
Respond with one JSON object and nothing else (no Markdown fences, no commentary).
Use exactly this shape:
{
  "project_name": string|null,
  "assumed_team_size": number|null,
  "mentioned_technologies": string[],
  "agreed_scope": string|null
}
Rules:
- Only keep facts supported by the user description and the estimation JSON.
- Merge with previous_metadata: refine or fill gaps; do not drop known facts unless
  the new turn clearly corrects them.
- mentioned_technologies must be a deduplicated list (empty list if none).
- assumed_team_size must be a positive integer when present.
- Do not invent budgets, rates or requirements that are not evidenced.
"""


def _parse_metadata_json(raw: str) -> ProjectMetadata:
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    payload = json.loads(text)
    return ProjectMetadata.model_validate(payload)


async def extract_project_metadata(
    *,
    description: str,
    estimation: str,
    current: ProjectMetadata,
) -> ProjectMetadata:
    """Devuelve metadata actualizada. Ante fallo del extractor conserva `current`."""
    settings = get_settings()
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"<previous_metadata>\n{current.model_dump_json()}\n</previous_metadata>\n\n"
                f"<user_description>\n{description}\n</user_description>\n\n"
                f"<estimation>\n{estimation}\n</estimation>\n\n"
                "Return the updated project metadata JSON object."
            ),
        },
    ]
    try:
        response = await complete(settings, messages)
        if not response.choices:
            raise RuntimeError("El extractor no devolvió choices.")
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise RuntimeError("El extractor no completó la respuesta.")
        content = choice.message.content
        if content is None or not content.strip():
            raise RuntimeError("El extractor devolvió contenido vacío.")
        return _parse_metadata_json(content)
    except (APIError, RuntimeError, ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            "metadata_extraction_failed",
            error_type=type(exc).__name__,
        )
        return current
