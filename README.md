# Estimador CAG

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
de `context/` directamente en el mensaje de sistema de la llamada a OpenAI.

Para arrancar en desarrollo:

```sh
uv sync
uv run uvicorn app.main:app --reload
```

Con el servidor arrancado y una clave válida configurada en `.env`, puedes
probar el endpoint mediante curl (realiza una llamada real a OpenAI):

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
Configura `OPENAI_API_KEY` y `LLM_PROVIDER=openai` en `.env`.

Los servicios pueden obtener la configuración validada con
`from app.config import get_settings`. La configuración se carga una vez al
llamar a `get_settings()` y las claves se representan ocultas mediante `SecretStr`.
