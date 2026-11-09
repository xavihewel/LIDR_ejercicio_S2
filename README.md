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

Abre `http://localhost:8501`. El formulario recoge descripción (transcript), tipo
de proyecto, nivel de detalle, formato de salida y adjuntos opcionales (PDF,
TXT, MD). «Enviar» abre `POST /sessions` si aún no hay `session_id`, y luego
envía `multipart/form-data` a `POST /sessions/{session_id}/estimate`. El cliente
no necesita claves LLM ni conexión directa a Redis. Cambiar campos no envía
peticiones hasta pulsar «Enviar».

El panel lateral muestra el `project_metadata` actual (memoria de sesión),
separado del historial/estimación del panel principal. «Nueva conversación»
vuelve a llamar a `POST /sessions` y resetea el estado del cliente.

El resultado se muestra como Markdown y se conserva al refrescar los widgets.
Los errores de validación, conexión, timeout y respuesta inválida se muestran
en la interfaz. El formulario espera la respuesta completa; el servicio sigue
ofreciendo generación en streaming como función Python compartida.

## Sesiones y adjuntos (camino B)

`POST /sessions` crea una sesión en memoria del proceso y responde
`{"session_id": "<uuid-v4>"}`. `GET /sessions/{session_id}` devuelve ese id y el
`project_metadata` actual. El estado se pierde al reiniciar el servicio
(sin BBDD ni Redis para el hilo conversacional). La historia usa una ventana
deslizante de `SESSION_MAX_TURNS` pares user+assistant (6 por defecto); el
system prompt es invariante y `messages_for_llm()` / `to_messages_list()`
regeneran el system con el `project_metadata` actual y acotan el historial
efectivo enviado al LLM.

`POST /sessions/{session_id}/estimate` acepta `multipart/form-data`:

| Campo | Obligatorio | Descripción |
| --- | --- | --- |
| `transcript` | sí | Texto 20–2000 caracteres |
| `project_type`, `detail_level`, `output_format` | sí | Mismos enums que el contrato JSON |
| `attachments` | no | Hasta 5 ficheros, 5 MB cada uno (`.pdf`, `.txt`, `.md`) |

**Camino B (extracción local):** el servicio extrae el texto con `pypdf` (PDF) o
UTF-8 (texto/markdown) y lo concatena al transcript con separadores
`--- attachment: filename ---` antes de renderizar el prompt. Solo viaja texto
al LLM. Se eligió B frente al multimodal nativo del proveedor para no acoplar
el wrapper a Files API, controlar qué entra al contexto y dejar lista la
extracción como primer paso hacia RAG. No se interpretan diagramas embebidos.

`POST /estimate` (JSON) sigue disponible para estimaciones sin ficheros; puede
llevar cabecera `X-Session-ID` para acumular turnos. Sesión desconocida → 404.
Adjunto no soportado o demasiado grande → 422.

### Memoria de sesión (`project_metadata`)

Tras cada estimación con sesión, una **segunda llamada al LLM** (extractor)
devuelve un JSON con `project_name`, `assumed_team_size`,
`mentioned_technologies` y `agreed_scope`. Ese objeto actualiza
`session.metadata` y en el siguiente turno se inyecta en el system prompt como
`<project_metadata>`.

Se eligió el extractor LLM frente a una heurística regex porque los hechos
salen de prosa libre (transcript, adjuntos y estimación) y el modelo ya valida
JSON en el flujo principal; la robustez compensa el coste/latencia de un turno
extra. Si el extractor falla (JSON inválido o error del proveedor), se conserva
la metadata anterior y la estimación sigue siendo válida.

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

Respuesta validada. `text` es el Markdown generado en el servidor a partir del
desglose; el cuerpo incluye solo el objeto del formato pedido. `prompt_version`
es `v2`.

```json
{
  "text": "## Estimación\n\n| phase | duration_weeks | cost_eur | confidence_pct |\n| --- | --- | --- | --- |\n| Diseño | 2 | 1000 | 70 |\n\n**Duración total:** 2 semanas",
  "prompt_version": "v2",
  "output_format": "phases_table",
  "phases_table": {
    "phases": [
      {"phase": "Diseño", "duration_weeks": 2, "cost_eur": 1000, "confidence_pct": 70}
    ],
    "total_duration_weeks": 2
  },
  "line_items": null,
  "narrative": null
}
```

`phases_table` exige que `total_duration_weeks` sea la suma de las fases.
`line_items` exige que `total_hours` sea la suma de las tareas. `narrative`
exige `overview`, `breakdown` y `risks` con texto. Un JSON inválido o un total
que no cuadra no se guarda en caché y la API responde 502. Entradas inválidas
reciben 422; configuración incorrecta, 503; errores del proveedor, 502;
timeout del proveedor, 504. `/api/v1/estimate` permanece como alias del endpoint,
con el mismo contrato. El servicio solo acepta `EstimationRequest`: un texto
suelto ya no se convierte en una petición con opciones por defecto.

`GET /health` no consulta al proveedor y funciona sin claves LLM. La documentación
OpenAPI del contrato está en `http://localhost:8000/docs`.

## Prompts y servicio

`app/prompts/loader.py` expone:

```python
render_estimation_prompt(request, version="v2") -> tuple[str, str]
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

Cada render correcto del loader emite `prompt_rendered` a nivel INFO con
`prompt_version` y `prompt_hash`. El hash es SHA-256 del JSON UTF-8 de los
mensajes `system` y `user`, con claves ordenadas. Permite comparar el contenido
renderizado sin escribirlo en logs; cambia si cambia cualquiera de los mensajes.
El evento hereda el `request_id` HTTP cuando está disponible. Un fallo de
renderizado no emite este evento de éxito.
