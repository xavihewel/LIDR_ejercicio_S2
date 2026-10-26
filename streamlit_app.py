"""Chat para estimar software a partir de transcripciones de reuniones."""

import streamlit as st
from openai import APIError, APITimeoutError

from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import EstimationMetrics, build_system_prompt, stream_estimation


def render_history() -> None:
    """Muestra los turnos guardados sin repetir llamadas al proveedor."""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def render_estimation(transcription: str, metrics: EstimationMetrics) -> str:
    """Muestra el stream y traduce los errores del proveedor para el usuario."""
    with st.chat_message("assistant"):
        response = st.empty()
        with st.spinner("Generando estimación…"):
            try:
                with response.container():
                    estimation = st.write_stream(
                        stream_estimation(transcription, metrics=metrics)
                    )
            except APITimeoutError:
                estimation = "El proveedor LLM no respondió a tiempo. Vuelve a enviar la transcripción."
            except (APIError, RuntimeError):
                estimation = "No se pudo obtener la estimación. Vuelve a intentarlo."
            except ValueError:
                estimation = (
                    "Revisa la configuración del servicio: OPENAI_API_KEY, "
                    "LLM_PROVIDER=openai y LLM_MODEL en el archivo .env."
                )
        response.markdown(estimation)
    return estimation


def process_transcription(transcription: str) -> None:
    """Registra un nuevo turno con métricas independientes."""
    metrics = EstimationMetrics()
    st.session_state.last_metrics = metrics
    st.session_state.messages.append({"role": "user", "content": transcription})
    with st.chat_message("user"):
        st.markdown(transcription)

    estimation = render_estimation(transcription, metrics)
    st.session_state.messages.append({"role": "assistant", "content": estimation})


def render_sidebar() -> None:
    """Muestra el contexto activo y las métricas de la última llamada."""
    with st.sidebar:
        st.header("Información del estimador")
        with st.expander("System prompt activo"):
            st.caption("Mensaje de sistema completo enviado al modelo, incluidos los ejemplos.")
            st.code(build_system_prompt(), language=None, wrap_lines=True)

        with st.expander("Contexto estático CAG"):
            for index, example in enumerate(ESTIMATION_EXAMPLES, start=1):
                st.subheader(f"Ejemplo {index}")
                st.markdown(example["meeting_summary"])
                st.markdown(example["estimation"].strip())

        st.subheader("Última llamada")
        last_metrics = st.session_state.get("last_metrics")
        if last_metrics is None:
            st.caption("Las métricas aparecerán después de enviar una transcripción.")
        else:
            st.metric("Modelo utilizado", last_metrics.model or "No disponible")
            for label, value in (
                ("Tokens de entrada", last_metrics.input_tokens),
                ("Tokens de salida", last_metrics.output_tokens),
            ):
                st.metric(label, value if value is not None else "No disponible")
            elapsed = last_metrics.response_seconds
            st.metric(
                "Tiempo de respuesta",
                f"{elapsed:.2f} s" if elapsed is not None else "No disponible",
            )
            st.caption(
                "Tiempo total de generación. Los tokens de entrada incluyen el prompt, "
                "el contexto CAG y la transcripción. Si el proveedor no informa del uso, "
                "se muestra «No disponible»."
            )


def main() -> None:
    st.set_page_config(page_title="Estimador CAG", page_icon="💬")
    st.title("Estimador de software")
    st.write("Escribe o pega la transcripción de una reunión para obtener su estimación.")
    if "messages" not in st.session_state:
        st.session_state.messages = []

    render_history()
    transcription = st.chat_input("Escribe o pega la transcripción de la reunión")
    if transcription is not None:
        if transcription.strip():
            process_transcription(transcription)
        else:
            st.warning("La transcripción no puede estar vacía.")
    render_sidebar()


if __name__ == "__main__":
    main()
