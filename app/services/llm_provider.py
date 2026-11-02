"""Acceso uniforme a OpenAI y Anthropic mediante LiteLLM."""

from litellm import acompletion
from openai.types.chat import ChatCompletionMessageParam

from app.config import Settings


async def complete(
    settings: Settings,
    messages: list[ChatCompletionMessageParam],
    *,
    stream: bool = False,
):
    """Selecciona proveedor y credenciales sin modificar el entorno del proceso."""
    key = getattr(settings, f"{settings.llm_provider}_api_key")
    if key is None or not key.get_secret_value().strip():
        raise ValueError(f"{settings.llm_provider.upper()}_API_KEY es obligatoria.")
    options = {"stream_options": {"include_usage": True}} if stream else {}
    return await acompletion(
        model=settings.llm_model,
        custom_llm_provider=settings.llm_provider,
        api_key=key.get_secret_value(),
        messages=messages,
        stream=stream,
        **options,
    )
