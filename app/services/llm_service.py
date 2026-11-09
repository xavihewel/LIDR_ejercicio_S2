"""Generación de estimaciones con contexto incluido directamente en la llamada."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from time import perf_counter

from openai.types.chat import ChatCompletionMessageParam

from app.observability import observe_estimation
from app.config import get_settings
from app.prompts.loader import render_estimation_prompt
from app.schemas import EstimationRequest
from app.services.llm_provider import complete
from app.services.llm_cache import CachedEstimation, LLMCache
from app.services.output_guardrails import parse_estimation


@dataclass
class EstimationMetrics:
    """Datos reales de la última llamada; None indica un dato no disponible."""

    cache_hit: bool = False
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_seconds: float | None = None


def _require_request(request: EstimationRequest) -> EstimationRequest:
    if not isinstance(request, EstimationRequest):
        raise TypeError("La estimación exige un EstimationRequest.")
    return request


def _messages(
    request: EstimationRequest, prompt: tuple[str, str] | None
) -> list[ChatCompletionMessageParam]:
    """Usa el prompt ya renderizado o el de la versión por defecto."""
    system, user = prompt if prompt is not None else render_estimation_prompt(request)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _validated_content(content: str | None, finish_reason: str | None, request: EstimationRequest) -> str:
    """Rechaza cierres incompletos, texto vacío y JSON que no cumple el formato."""
    if finish_reason != "stop":
        raise RuntimeError("El modelo no pudo completar la estimación.")
    if content is None or not content.strip():
        raise RuntimeError("El modelo devolvió una estimación vacía.")
    parse_estimation(content, request.output_format)
    return content


def _usable_cache(content: str, request: EstimationRequest) -> bool:
    try:
        parse_estimation(content, request.output_format)
    except RuntimeError:
        return False
    return True


class _Call:
    """Prepara mensajes, clave de caché y el cliente Redis de una estimación."""

    def __init__(self, request: EstimationRequest, prompt: tuple[str, str] | None):
        self.request = request
        self.settings = get_settings()
        self.messages = _messages(request, prompt)
        self.cache = LLMCache(self.settings.redis_url, self.settings.cache_ttl)
        self.key = self.cache.cache_key(
            self.messages, self.settings.llm_model, self.settings.llm_provider
        )

    async def read_cache(self) -> CachedEstimation | None:
        if not self.settings.cache_enabled:
            return None
        cached = await self.cache.get(self.key)
        if cached is None or not _usable_cache(cached.content, self.request):
            return None
        return cached

    async def store(self, content: str, model: str, tokens_in: int | None, tokens_out: int | None) -> None:
        if not self.settings.cache_enabled:
            return
        await self.cache.set(self.key, CachedEstimation(
            content=content, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
        ))


def _remember_hit(metrics: EstimationMetrics, cached: CachedEstimation) -> None:
    metrics.cache_hit = True
    metrics.model = cached.model
    metrics.input_tokens = cached.tokens_in
    metrics.output_tokens = cached.tokens_out


async def _generate_estimation(
    request: EstimationRequest, metrics: EstimationMetrics,
    *, prompt: tuple[str, str] | None = None,
) -> str:
    """Devuelve el JSON validado. Un acierto no llama al proveedor."""
    call = _Call(request, prompt)
    metrics.model = call.settings.llm_model
    cached = await call.read_cache()
    if cached is not None:
        _remember_hit(metrics, cached)
        return cached.content

    response = await complete(call.settings, call.messages)
    if not response.choices:
        raise RuntimeError("El modelo no devolvió ninguna estimación.")
    choice = response.choices[0]
    content = _validated_content(choice.message.content, choice.finish_reason, request)
    usage = getattr(response, "usage", None)
    metrics.model = getattr(response, "model", None) or call.settings.llm_model
    metrics.input_tokens = usage.prompt_tokens if usage else None
    metrics.output_tokens = usage.completion_tokens if usage else None
    await call.store(
        content, metrics.model, metrics.input_tokens, metrics.output_tokens,
    )
    return content


async def _stream_estimation(
    request: EstimationRequest, *, metrics: EstimationMetrics, prompt: tuple[str, str] | None = None,
) -> AsyncIterator[str]:
    """Entrega fragmentos y solo guarda el JSON cuando el stream cierra bien."""
    metrics.cache_hit = False
    metrics.model = None
    metrics.input_tokens = None
    metrics.output_tokens = None
    metrics.response_seconds = None
    started = perf_counter()
    try:
        call = _Call(request, prompt)
        metrics.model = call.settings.llm_model
        cached = await call.read_cache()
        if cached is not None:
            _remember_hit(metrics, cached)
            yield cached.content
            return
        stream = await complete(call.settings, call.messages, stream=True)
        parts: list[str] = []
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
            content = _validated_content("".join(parts) if has_text else None, finish_reason, request)
        await call.store(content, metrics.model, metrics.input_tokens, metrics.output_tokens)
    finally:
        metrics.response_seconds = perf_counter() - started


async def generate_estimation(
    request: EstimationRequest, *, prompt: tuple[str, str] | None = None
) -> str:
    """Genera el JSON de la estimación y registra duración, consumo y resultado."""
    _require_request(request)
    metrics = EstimationMetrics()
    with observe_estimation(metrics, streaming=False) as fields:
        fields["provider"] = get_settings().llm_provider
        return await _generate_estimation(request, metrics, prompt=prompt)


async def stream_estimation(
    request: EstimationRequest,
    *,
    metrics: EstimationMetrics | None = None,
    prompt: tuple[str, str] | None = None,
) -> AsyncIterator[str]:
    """Lee al proveedor en streaming. El endpoint HTTP espera el JSON completo."""
    _require_request(request)
    metrics = metrics if metrics is not None else EstimationMetrics()
    with observe_estimation(metrics, streaming=True) as fields:
        fields["provider"] = get_settings().llm_provider
        async with aclosing(_stream_estimation(request, metrics=metrics, prompt=prompt)) as stream:
            async for part in stream:
                yield part
