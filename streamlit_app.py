"""Chat para estimar software a partir de transcripciones de reuniones."""

import streamlit as st
from openai import APIError, APITimeoutError

from app.services.llm_service import stream_estimation


st.set_page_config(page_title="Estimador CAG", page_icon="💬")
st.title("Estimador de software")
st.write("Escribe o pega la transcripción de una reunión para obtener su estimación.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

transcription = st.chat_input("Escribe o pega la transcripción de la reunión")
if transcription is not None:
    if not transcription.strip():
        st.warning("La transcripción no puede estar vacía.")
    else:
        st.session_state.messages.append({"role": "user", "content": transcription})
        with st.chat_message("user"):
            st.markdown(transcription)

        with st.chat_message("assistant"):
            response = st.empty()
            with st.spinner("Generando estimación…"):
                try:
                    with response.container():
                        estimation = st.write_stream(stream_estimation(transcription))
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
        st.session_state.messages.append({"role": "assistant", "content": estimation})
