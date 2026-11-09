"""Contrato Pydantic v2 compartido por la API y el formulario."""
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator


class ProjectType(StrEnum):
    SOFTWARE = "software"
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(StrEnum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(StrEnum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


class EstimationRequest(BaseModel):
    description: str = Field(min_length=20, max_length=2000)
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat

    @field_validator("description")
    @classmethod
    def nonblank_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("La descripción no puede estar vacía.")
        return value


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("El texto no puede estar vacío.")
    return value


class PhaseRow(BaseModel):
    phase: str = Field(min_length=1)
    duration_weeks: float = Field(gt=0)
    cost_eur: float = Field(ge=0)
    confidence_pct: float = Field(ge=0, le=100)

    @field_validator("phase")
    @classmethod
    def phase_has_text(cls, value: str) -> str:
        return _nonblank(value)


class PhasesTableEstimate(BaseModel):
    phases: list[PhaseRow] = Field(min_length=1)
    total_duration_weeks: float = Field(gt=0)

    @model_validator(mode="after")
    def total_matches_phases(self) -> Self:
        total = sum(row.duration_weeks for row in self.phases)
        if abs(total - self.total_duration_weeks) > 0.01:
            raise ValueError("La duración total no coincide con la suma de las fases.")
        return self


class LineItem(BaseModel):
    task: str = Field(min_length=1)
    hours: float = Field(gt=0)
    assumptions: str = Field(min_length=1)
    risks: str = Field(min_length=1)

    @field_validator("task", "assumptions", "risks")
    @classmethod
    def item_text_has_content(cls, value: str) -> str:
        return _nonblank(value)


class LineItemsEstimate(BaseModel):
    items: list[LineItem] = Field(min_length=1)
    total_hours: float = Field(gt=0)

    @model_validator(mode="after")
    def total_matches_items(self) -> Self:
        total = sum(item.hours for item in self.items)
        if abs(total - self.total_hours) > 0.01:
            raise ValueError("El total de horas no coincide con la suma de las tareas.")
        return self


class NarrativeEstimate(BaseModel):
    overview: str = Field(min_length=1)
    breakdown: str = Field(min_length=1)
    risks: str = Field(min_length=1)

    @field_validator("overview", "breakdown", "risks")
    @classmethod
    def section_has_text(cls, value: str) -> str:
        return _nonblank(value)


class EstimationResponse(BaseModel):
    text: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    output_format: OutputFormat
    phases_table: PhasesTableEstimate | None = None
    line_items: LineItemsEstimate | None = None
    narrative: NarrativeEstimate | None = None

    @model_validator(mode="after")
    def body_matches_format(self) -> Self:
        bodies = {
            OutputFormat.PHASES_TABLE: self.phases_table,
            OutputFormat.LINE_ITEMS: self.line_items,
            OutputFormat.NARRATIVE: self.narrative,
        }
        selected = bodies[self.output_format]
        others = [body for fmt, body in bodies.items() if fmt != self.output_format and body is not None]
        if selected is None or others:
            raise ValueError("La respuesta debe incluir solo el desglose del formato pedido.")
        return self
