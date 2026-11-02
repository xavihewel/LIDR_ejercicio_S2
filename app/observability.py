"""Configuración JSON y eventos de ejecución sin datos de negocio."""

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import asdict
from time import perf_counter
from typing import Literal

import structlog
from pydantic_settings import BaseSettings

from app.config import Settings


class LoggingSettings(BaseSettings):
    model_config = Settings.model_config
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"


def configure_logging(log_level: str | None = None, *, output=None) -> None:
    level = log_level or LoggingSettings().log_level
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=output),
        cache_logger_on_first_use=False,
    )


@contextmanager
def observe_estimation(metrics, *, streaming: bool):
    """Registra un único resultado incluso ante errores o cancelación del stream."""
    started = perf_counter()
    fields = {"streaming": streaming}
    event = "estimation_completed"
    level = "info"
    logger = structlog.get_logger(__name__)
    try:
        yield fields
    except (GeneratorExit, asyncio.CancelledError):
        event = "estimation_cancelled"
        raise
    except Exception as exc:
        event, level = "estimation_failed", "error"
        fields["error_type"] = type(exc).__name__
        raise
    finally:
        values = asdict(metrics)
        values.pop("response_seconds")
        getattr(logger, level)(
            event, **fields, **values, duration_seconds=perf_counter() - started
        )
