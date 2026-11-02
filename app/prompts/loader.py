"""Renderizado de prompts de estimación organizados por versión."""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas import EstimationRequest
from app.context.examples import ESTIMATION_EXAMPLES

DEFAULT_PROMPT_VERSION = "v1"

PROMPTS_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = DEFAULT_PROMPT_VERSION,
) -> tuple[str, str]:
    """Devuelve los mensajes system y user de estimation/<version>/."""
    template_dir = f"estimation/{version}"
    system = _env.get_template(f"{template_dir}/system.j2")
    user = _env.get_template(f"{template_dir}/user.j2")

    context = {
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "description": request.description,
        "examples": ESTIMATION_EXAMPLES,
        "examples_template": f"{template_dir}/examples.j2",
    }

    return system.render(**context), user.render(**context)
