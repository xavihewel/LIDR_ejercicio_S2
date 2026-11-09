"""Validación programática de la salida del modelo y su vista Markdown."""
import json
import re

from pydantic import ValidationError

from app.schemas import (
    EstimationRequest,
    EstimationResponse,
    LineItemsEstimate,
    NarrativeEstimate,
    OutputFormat,
    PhasesTableEstimate,
)

_MODELS = {
    OutputFormat.PHASES_TABLE: PhasesTableEstimate,
    OutputFormat.LINE_ITEMS: LineItemsEstimate,
    OutputFormat.NARRATIVE: NarrativeEstimate,
}
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_estimation(raw: str, output_format: OutputFormat):
    """Acepta el JSON del modelo, con o sin un único bloque cercado."""
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("La estimación no es JSON válido.") from exc
    try:
        return _MODELS[output_format].model_validate(payload)
    except ValidationError as exc:
        raise RuntimeError("La estimación no cumple el formato solicitado.") from exc


def render_estimation_text(estimate, output_format: OutputFormat) -> str:
    """Construye el Markdown que muestra el cliente a partir del objeto validado."""
    if output_format == OutputFormat.PHASES_TABLE:
        rows = [
            f"| {row.phase} | {row.duration_weeks:g} | {row.cost_eur:g} | {row.confidence_pct:g} |"
            for row in estimate.phases
        ]
        table = "\n".join([
            "| phase | duration_weeks | cost_eur | confidence_pct |",
            "| --- | --- | --- | --- |",
            *rows,
        ])
        return f"## Estimación\n\n{table}\n\n**Duración total:** {estimate.total_duration_weeks:g} semanas"
    if output_format == OutputFormat.LINE_ITEMS:
        tasks = [
            (
                f"{index}. **{item.task}** — {item.hours:g} h\n"
                f"   - Supuestos: {item.assumptions}\n"
                f"   - Riesgos: {item.risks}"
            )
            for index, item in enumerate(estimate.items, start=1)
        ]
        return f"## Estimación\n\n" + "\n".join(tasks) + f"\n\n**Total:** {estimate.total_hours:g} horas"
    return "\n\n".join(["## Estimación", estimate.overview, estimate.breakdown, estimate.risks])


def build_estimation_response(
    raw: str, request: EstimationRequest, prompt_version: str
) -> EstimationResponse:
    """Une el desglose validado con la versión del prompt y su Markdown."""
    parsed = parse_estimation(raw, request.output_format)
    bodies = {
        OutputFormat.PHASES_TABLE: "phases_table",
        OutputFormat.LINE_ITEMS: "line_items",
        OutputFormat.NARRATIVE: "narrative",
    }
    return EstimationResponse(
        text=render_estimation_text(parsed, request.output_format),
        prompt_version=prompt_version,
        output_format=request.output_format,
        **{bodies[request.output_format]: parsed},
    )
