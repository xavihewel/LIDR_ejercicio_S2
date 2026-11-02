# Estimador CAG

Servicio FastAPI de estimación de software con LiteLLM, ejemplos CAG,
plantillas Jinja2, caché exact-match Redis y logs JSON con structlog.
El cliente Streamlit usa un formulario y consume el servicio por HTTP.

Las directrices de desarrollo están en `AGENTS.md`. Se sigue TDD para los
cambios de comportamiento. Las pruebas no necesitan proveedores ni Redis reales:

```sh
uv sync
uv run python -m unittest discover -s tests -v
```

## Arranque

Copia `.env.example` a `.env` y configura el proveedor, modelo y clave del
servicio. `.env` está excluido de Git.

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=tu-clave-local
REDIS_URL=redis://localhost:6379
CACHE_TTL=86400
CACHE_ENABLED=true
LOG_LEVEL=INFO
ESTIMATION_API_URL=http://localhost:8000
```

Para Anthropic, usa `LLM_PROVIDER=anthropic`, un modelo compatible disponible
en tu cuenta y `ANTHROPIC_API_KEY`. Solo es necesaria la clave del proveedor
seleccionado. El wrapper pasa proveedor y credenciales explícitamente a LiteLLM.

Arranca el servicio y el cliente en terminales separadas:

```sh
uv run uvicorn app.main:app --reload
```

```sh
uv run streamlit run streamlit_app.py
```

Abre `http://localhost:8501`. El formulario recoge descripción, tipo de proyecto,
nivel de detalle y formato de salida. «Enviar» crea un `EstimationRequest`, lo
serializa con `model_dump(mode="json")` y hace `POST /estimate` a
`ESTIMATION_API_URL`. El cliente no necesita claves LLM ni conexión directa a
Redis; puede ejecutarse en otro proceso o equipo. Cambiar campos no envía
peticiones hasta pulsar «Enviar».

El resultado se muestra como Markdown y se conserva al refrescar los widgets.
Los errores de validación, conexión, timeout y respuesta inválida se muestran
en la interfaz. El formulario espera la respuesta completa; el servicio sigue
ofreciendo generación en streaming como función Python compartida.

## Contrato Pydantic v2

La fuente única es `app/schemas/estimation.py`, reexportada por `app.schemas`
y reutilizada por el cliente. Los cuatro campos de entrada son obligatorios:

| Campo | Valores |
| --- | --- |
| `description` | Texto de 20 a 2000 caracteres; no puede contener solo espacios |
| `project_type` | `software`, `mobile_app`, `web_saas`, `internal_tool`, `data_pipeline` |
| `detail_level` | `summary`, `medium`, `detailed` |
| `output_format` | `phases_table`, `line_items`, `narrative` |

```sh
curl -X POST http://localhost:8000/estimate \
  -H 'Content-Type: application/json' \
  -d '{"description":"Aplicación móvil con login, chat y notificaciones push.","project_type":"mobile_app","detail_level":"detailed","output_format":"phases_table"}'
```

Respuesta:

```json
{
  "text": "## Estimación\n\nTexto libre generado por el modelo...",
  "prompt_version": "v1"
}
```

`text` sigue siendo texto libre: no se valida todavía un desglose estructurado.
La API valida el contrato antes de llamar al proveedor. Entradas inválidas
reciben 422; configuración incorrecta, 503; errores del proveedor, 502;
timeout del proveedor, 504. `/api/v1/estimate` permanece como alias del endpoint,
con el mismo contrato nuevo. El anterior cuerpo con `transcription` y la
respuesta con `estimation`, `model` y `provider` se sustituyen por este contrato.

`GET /health` no consulta al proveedor y funciona sin claves LLM. La documentación
OpenAPI del contrato está en `http://localhost:8000/docs`.

## Prompts y servicio

`app/prompts/loader.py` expone:

```python
render_estimation_prompt(request, version="v1") -> tuple[str, str]
```

Devuelve `(system, user)` listos para enviar al modelo. Usa Jinja2 con
`StrictUndefined`, `trim_blocks=True` y `lstrip_blocks=True`. Cada versión vive
en `app/prompts/estimation/<version>/` y contiene `system.j2`, `user.j2` y
`examples.j2`. `{% include examples_template %}` selecciona los ejemplos de la
misma versión. El contexto CAG procede de `app/context/examples.py`.

El servicio renderiza mensajes separados para sistema y usuario, incluyendo la
descripción dentro de `<project_description>`. Las opciones del formulario
controlan el tipo de proyecto, detalle y formato. LiteLLM abstrae OpenAI y
Anthropic tanto en generación completa como en streaming. La dirección de las
dependencias es `router → servicio → loader/proveedor/caché`; Streamlit solo
importa el contrato y usa HTTP.

## Caché exact-match

Para arrancar Redis localmente:

```sh
docker run --name estimador-redis -p 6379:6379 -d redis:7-alpine
```

La clave es un SHA-256 de los mensajes renderizados completos, modelo y
proveedor. Cualquier cambio en descripción, opciones o plantillas que afecte
los mensajes genera otra clave. Se conservan los espacios de la descripción.
Los modos completo y streaming comparten la caché, con TTL de 86400 segundos
por defecto. `CACHE_TTL` debe ser positivo; `CACHE_ENABLED=false` desactiva
lecturas y escrituras.

Solo se guardan respuestas válidas y completas. Un stream truncado o cancelado
no se guarda. Un acierto no llama al proveedor y devuelve el texto almacenado.
Si Redis falla o una entrada está corrupta, se continúa con el proveedor.

## Observabilidad

FastAPI emite logs JSON a la salida estándar con structlog. `LOG_LEVEL` controla
el nivel mínimo. Cada petición tiene un ID generado por el servidor, devuelto
en `X-Request-ID` y propagado a los logs del servicio y Redis.

Los eventos HTTP registran método, ruta, estado y duración cuando están
disponibles. Las estimaciones registran proveedor, modelo, duración, modo,
`cache_hit` y tokens disponibles. Los tokens de un acierto corresponden a la
generación original, sin nuevo consumo. También se registran cancelaciones,
fallos de caché y errores de estimación. Los logs propios no incluyen prompts,
transcripciones, respuestas, claves, URL de Redis ni mensajes de excepción;
los errores incluyen únicamente `error_type`. Las librerías externas conservan
su propia configuración de logs.
