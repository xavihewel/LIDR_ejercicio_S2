from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas import EstimationRequest
from app.context.examples import ESTIMATION_EXAMPLES

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
    version: str = "v1",
) -> tuple[str, str]:
    system = _env.get_template(f"{version}/system.j2")
    user = _env.get_template(f"{version}/user.j2")

    context = {
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "description": request.description,
        "examples": ESTIMATION_EXAMPLES,
    }

    return system.render(**context), user.render(**context)
