# Estimador CAG

Las directrices de desarrollo están en `AGENTS.md`. Para los cambios de
comportamiento se sigue TDD: reproducir el caso con una prueba que falle,
implementar la corrección y refactorizar con las pruebas en verde.
Para ejecutar las pruebas sin llamadas reales al LLM:

```sh
uv run python -m unittest discover -s tests -v
```

```text
estimador-cag/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── routers/
│   │   ├── __init__.py
│   │   └── estimations.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_provider.py
│   │   └── llm_service.py
│   └── context/
│       ├── __init__.py
│       └── examples.py
├── .env
├── .env.example
├── .gitignore
├── pyproject.toml
├── streamlit_app.py
└── README.md
```

`main.py` crea la aplicación FastAPI y registra los routers. `config.py`
define la configuración mediante variables de entorno y `.env`.
`.env` es local y está excluido de Git; `.env.example` sirve como plantilla.

Los routers gestionan HTTP y delegan la lógica de negocio en los servicios.
Los servicios preparan el prompt con los datos estáticos de `context/` y llaman
al LLM. La dirección de dependencias es `routers → services → context`.
Esta separación es una decisión arquitectónica deliberada para facilitar
la evolución y las pruebas independientes de cada responsabilidad.

`POST /api/v1/estimate` recibe una transcripción y devuelve la estimación,
el modelo y el proveedor configurados. El servicio incluye los ejemplos
de `context/` directamente en el mensaje de sistema. El wrapper
`llm_provider.py` utiliza `litellm.acompletion` para abstraer OpenAI y Anthropic,
tanto en respuestas completas como en streaming.

Para arrancar en desarrollo:

```sh
uv sync
uv run uvicorn app.main:app --reload
```

Con el servidor arrancado y una clave válida configurada en `.env`, puedes
probar el endpoint mediante curl (realiza una llamada real al proveedor configurado):

```sh
curl -X POST http://127.0.0.1:8000/api/v1/estimate \
  -H 'Content-Type: application/json' \
  -d '{"transcription":"En la reunión con el cliente se discutió la necesidad de una plataforma de gestión de inventario con autenticación y un panel de métricas."}'
```

La respuesta JSON contiene `estimation`, `model` y `provider`. Las peticiones
sin una transcripción de texto no vacía reciben un error 422. Los errores de
configuración devuelven 503; los del proveedor, 502 o 504 si agota el tiempo.
La documentación interactiva está disponible en `http://127.0.0.1:8000/docs`.

Configura `OPENAI_API_KEY` en tu `.env` local. La plantilla `.env.example`
documenta todas las variables sin incluir valores. Se usa OpenAI por defecto,
con `LLM_MODEL=gpt-4o-mini`, `APP_ENV=development` y `LOG_LEVEL=DEBUG`.
Los valores vacíos permiten aplicar los valores por defecto.
`ANTHROPIC_API_KEY` solo es obligatoria si seleccionas `LLM_PROVIDER=anthropic`.
Al cambiar de proveedor, configura también un `LLM_MODEL` compatible disponible
en tu cuenta. Por ejemplo, para Anthropic:

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5-20250929
ANTHROPIC_API_KEY=tu-clave-local
```

El wrapper pasa explícitamente el proveedor y su clave a LiteLLM; no modifica
las variables de entorno ni necesita la clave del otro proveedor.

Para usar el chat de Streamlit:

```sh
uv sync
uv run streamlit run streamlit_app.py
```

Abre `http://localhost:8501` y escribe o pega una transcripción en el chat.
La estimación aparece progresivamente con `st.write_stream` como mensaje del
asistente y el historial se mantiene
visible durante la sesión mediante `st.session_state`. Cada transcripción
se estima de forma independiente. El chat llama directamente a
`stream_estimation` del servicio LLM compartido con el endpoint CAG y utiliza
exactamente su system prompt y sus ejemplos. No necesita arrancar FastAPI.
Configura el proveedor, su modelo y su clave en `.env`, como se indica arriba.

El panel lateral muestra el system prompt completo en solo lectura y las
estimaciones de ejemplo que forman el contexto CAG. Tras cada envío muestra
el modelo, los tokens de entrada y salida informados por el proveedor y el
tiempo total de generación en segundos. Las métricas se conservan durante
la sesión; si una llamada falla o no informa del consumo, los tokens aparecen
como «No disponible», sin reutilizar cifras de una llamada anterior.

Los servicios pueden obtener la configuración validada con
`from app.config import get_settings`. La configuración se carga una vez al
llamar a `get_settings()` y las claves se representan ocultas mediante `SecretStr`.

## Caché exact-match con Redis

FastAPI y Streamlit comparten una caché Redis de estimaciones completas, con
TTL de 24 horas. Configuración en `.env`:

```dotenv
REDIS_URL=redis://localhost:6379
CACHE_TTL=86400
CACHE_ENABLED=true
```

`CACHE_TTL` se expresa en segundos y debe ser positivo. Para arrancar Redis
localmente con Docker:

```sh
docker run --name estimador-redis -p 6379:6379 -d redis:7-alpine
```

La clave es un SHA-256 de los mensajes completos (incluidos el system prompt
y todos los ejemplos), el modelo y el proveedor. Solo las entradas idénticas
reutilizan la respuesta; cualquier cambio en el contexto, modelo, proveedor
o texto genera otra clave. El endpoint elimina los espacios de los extremos
antes de consultar el servicio, como parte de su validación existente.

Solo se guardan respuestas válidas y completas. En streaming, los fragmentos
se entregan inmediatamente y se guardan juntos al finalizar; las respuestas
interrumpidas o truncadas no se guardan. Un acierto devuelve el texto guardado
como un único fragmento y no llama al proveedor. Ambos modos comparten entradas.
El panel lateral indica si la respuesta procede de caché; los tokens mostrados
en ese caso son los de la generación original y no un nuevo consumo.

Si Redis no está disponible o una entrada está corrupta, el servicio continúa
con el proveedor y registra una advertencia sin incluir transcripciones ni
credenciales. `CACHE_ENABLED=false` desactiva las lecturas y escrituras.
