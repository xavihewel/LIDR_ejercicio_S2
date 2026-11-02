"""Entrada para el renderizado de prompts de estimación de proyectos."""

from enum import StrEnum

from pydantic import AliasChoices, BaseModel, Field, field_validator


class ProjectType(StrEnum):
    SOFTWARE = "software"
    MOBILE_APP = "mobile_app"


class DetailLevel(StrEnum):
    DETAILED = "detailed"


class OutputFormat(StrEnum):
    PHASES_TABLE = "phases_table"
    NARRATIVE = "narrative"


class EstimationRequest(BaseModel):
    description: str = Field(
        min_length=1, validation_alias=AliasChoices("description", "transcription")
    )
    project_type: ProjectType = ProjectType.SOFTWARE
    detail_level: DetailLevel = DetailLevel.DETAILED
    output_format: OutputFormat = OutputFormat.PHASES_TABLE

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("La descripción no puede estar vacía.")
        return value


class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
