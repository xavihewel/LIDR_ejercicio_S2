"""Generación de estimaciones con contexto incluido directamente en la llamada."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from time import perf_counter

from openai.types.chat import ChatCompletionMessageParam

from app.observability import observe_estimation
from app.config import Settings, get_settings
from app.prompts.loader import render_estimation_prompt
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.llm_provider import complete
from app.services.llm_cache import CachedEstimation, LLMCache


@dataclass
class EstimationMetrics:
    """Datos reales de la última llamada; None indica un dato no disponible."""

    cache_hit: bool = False
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_seconds: float | None = None


def build_system_prompt() -> str:
    """Devuelve el sistema de la plantilla usada por defecto en Streamlit."""
    system, _ = render_estimation_prompt(_estimation_request("Vista previa del sistema de estimación"))
    return system


def _estimation_settings(transcription: str | EstimationRequest) -> Settings:
    """Valida la entrada antes de acceder al proveedor o a Redis."""
    _estimation_request(transcription)
    return get_settings()


def _estimation_request(value: str | EstimationRequest) -> EstimationRequest:
    return value if isinstance(value, EstimationRequest) else EstimationRequest(
        description=value, project_type=ProjectType.SOFTWARE,
        detail_level=DetailLevel.DETAILED, output_format=OutputFormat.PHASES_TABLE,
    )


def _estimation_messages(
    transcription: str | EstimationRequest, *, prompt: tuple[str, str] | None = None
) -> list[ChatCompletionMessageParam]:
    """Renderiza el mismo prompt para ambos modos y para la clave de caché."""
    system, user = prompt if prompt is not None else render_estimation_prompt(_estimation_request(transcription))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _stream_estimation(
    transcription: str | EstimationRequest, *, metrics: EstimationMetrics | None = None
) -> AsyncIterator[str]:
    """Entrega fragmentos de texto conforme llegan y valida el cierre del stream."""
    metrics = metrics if metrics is not None else EstimationMetrics()
    metrics.cache_hit = False
    metrics.model = None
    metrics.input_tokens = None
    metrics.output_tokens = None
    metrics.response_seconds = None
    started = perf_counter()
    try:
        settings = _estimation_settings(transcription)
        metrics.model = settings.llm_model
        messages = _estimation_messages(transcription)
        cache = LLMCache(settings.redis_url, settings.cache_ttl)
        key = cache.cache_key(messages, settings.llm_model, settings.llm_provider)
        cached = await cache.get(key) if settings.cache_enabled else None
        if cached is not None:
            metrics.cache_hit = True
            metrics.model = cached.model
            metrics.input_tokens = cached.tokens_in
            metrics.output_tokens = cached.tokens_out
            yield cached.content
            return
        stream = await complete(settings, messages, stream=True)
        parts = []
        async with aclosing(stream):
            has_text = False
            finish_reason = None
            async for chunk in stream:
                if getattr(chunk, "model", None):
                    metrics.model = chunk.model
                if getattr(chunk, "usage", None) is not None:
                    metrics.input_tokens = chunk.usage.prompt_tokens
                    metrics.output_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.delta.content:
                    has_text = has_text or bool(choice.delta.content.strip())
                    parts.append(choice.delta.content)
                    yield choice.delta.content
                if choice.finish_reason is not None:
                    finish_reason = choice.finish_reason
            if finish_reason != "stop":
                raise RuntimeError("El modelo no pudo completar la estimación.")
            if not has_text:
                raise RuntimeError("El modelo devolvió una estimación vacía.")
        if settings.cache_enabled:
            await cache.set(key, CachedEstimation(
                content="".join(parts), model=metrics.model,
                tokens_in=metrics.input_tokens, tokens_out=metrics.output_tokens,
            ))
    finally:
        metrics.response_seconds = perf_counter() - started


async def _generate_estimation(
    transcription: str | EstimationRequest, metrics: EstimationMetrics,
    *, prompt: tuple[str, str] | None = None,
) -> str:
    """Envía contexto y transcripción al proveedor configurado y devuelve la estimación.

    Rechaza transcripciones vacías y respuestas sin texto o incompletas.
    Los errores del SDK se propagan para que la capa HTTP pueda gestionarlos.
    """
    settings = _estimation_settings(transcription)

    metrics.model = settings.llm_model
    messages = _estimation_messages(transcription, prompt=prompt)
    cache = LLMCache(settings.redis_url, settings.cache_ttl)
    key = cache.cache_key(messages, settings.llm_model, settings.llm_provider)
    cached = await cache.get(key) if settings.cache_enabled else None
    if cached is not None:
        metrics.cache_hit = True
        metrics.model = cached.model
        metrics.input_tokens = cached.tokens_in
        metrics.output_tokens = cached.tokens_out
        return cached.content
    response = await complete(settings, messages)

    if not response.choices:
        raise RuntimeError("El modelo no devolvió ninguna estimación.")
    choice = response.choices[0]
    if choice.finish_reason != "stop":
        raise RuntimeError("El modelo no pudo completar la estimación.")
    content = choice.message.content
    if not content or not content.strip():
        raise RuntimeError("El modelo devolvió una estimación vacía.")
    usage = getattr(response, "usage", None)
    metrics.model = getattr(response, "model", None) or settings.llm_model
    metrics.input_tokens = usage.prompt_tokens if usage else None
    metrics.output_tokens = usage.completion_tokens if usage else None
    if settings.cache_enabled:
        await cache.set(key, CachedEstimation(
            content=content, model=getattr(response, "model", None) or settings.llm_model,
            tokens_in=usage.prompt_tokens if usage else None,
            tokens_out=usage.completion_tokens if usage else None,
        ))
    return content


async def generate_estimation(
    transcription: str | EstimationRequest, *, prompt: tuple[str, str] | None = None
) -> str:
    """Genera una estimación y registra duración, consumo y resultado."""
    metrics = EstimationMetrics()
    with observe_estimation(metrics, streaming=False) as fields:
        fields["provider"] = get_settings().llm_provider
        return await _generate_estimation(transcription, metrics, prompt=prompt)


async def stream_estimation(
    transcription: str | EstimationRequest, *, metrics: EstimationMetrics | None = None
) -> AsyncIterator[str]:
    """Observa todo el stream, incluido su cierre anticipado."""
    metrics = metrics if metrics is not None else EstimationMetrics()
    with observe_estimation(metrics, streaming=True) as fields:
        fields["provider"] = get_settings().llm_provider
        async with aclosing(_stream_estimation(transcription, metrics=metrics)) as stream:
            async for part in stream:
                yield part
