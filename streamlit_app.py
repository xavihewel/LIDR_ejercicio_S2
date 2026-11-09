"""Formulario cliente del servicio HTTP de estimaciones."""
from pathlib import Path

import httpx
import streamlit as st
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas import DetailLevel, EstimationRequest, EstimationResponse, OutputFormat, ProjectType


class ClientSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env", extra="ignore", env_ignore_empty=True,
    )
    estimation_api_url: str = "http://localhost:8000"


PROJECT_LABELS = {
    ProjectType.SOFTWARE: "Software general",
    ProjectType.MOBILE_APP: "Aplicación móvil",
    ProjectType.WEB_SAAS: "Web / SaaS",
    ProjectType.INTERNAL_TOOL: "Herramienta interna",
    ProjectType.DATA_PIPELINE: "Pipeline de datos",
}
DETAIL_LABELS = {DetailLevel.SUMMARY: "Resumen", DetailLevel.MEDIUM: "Medio", DetailLevel.DETAILED: "Detallado"}
FORMAT_LABELS = {OutputFormat.PHASES_TABLE: "Tabla por fases", OutputFormat.LINE_ITEMS: "Listado de tareas", OutputFormat.NARRATIVE: "Narrativo"}


def api_base_url() -> str:
    return ClientSettings().estimation_api_url.rstrip("/")


def ensure_session_id() -> str:
    """Abre POST /sessions una vez y reutiliza el id entre reruns de Streamlit."""
    session_id = st.session_state.get("session_id")
    if session_id:
        return session_id
    response = httpx.post(f"{api_base_url()}/sessions", timeout=30.0)
    response.raise_for_status()
    session_id = response.json()["session_id"]
    st.session_state.session_id = session_id
    return session_id


def submit_estimation(request: EstimationRequest, session_id: str) -> EstimationResponse:
    """Envía el contrato JSON con X-Session-ID; el cliente no necesita claves LLM."""
    response = httpx.post(
        f"{api_base_url()}/estimate",
        json=request.model_dump(mode="json"),
        headers={"X-Session-ID": session_id},
        timeout=120.0,
    )
    response.raise_for_status()
    return EstimationResponse.model_validate(response.json())


def main() -> None:
    st.set_page_config(page_title="Estimador CAG", page_icon="📝")
    st.title("Estimador de software")
    st.write("Describe tu proyecto y selecciona cómo quieres recibir la estimación.")
    with st.form("estimation_form"):
        description = st.text_area("Descripción del proyecto", max_chars=2000, height=180, help="Entre 20 y 2000 caracteres.")
        project_type = st.selectbox("Tipo de proyecto", list(ProjectType), format_func=PROJECT_LABELS.get)
        detail_level = st.selectbox("Nivel de detalle", list(DetailLevel), index=2, format_func=DETAIL_LABELS.get)
        output_format = st.selectbox("Formato de salida", list(OutputFormat), format_func=FORMAT_LABELS.get)
        submitted = st.form_submit_button("Enviar")

    if submitted:
        st.session_state.pop("estimation_result", None)
        try:
            request = EstimationRequest(
                description=description, project_type=project_type,
                detail_level=detail_level, output_format=output_format,
            )
        except ValidationError:
            st.error("Introduce una descripción de entre 20 y 2000 caracteres, con contenido.")
        else:
            with st.spinner("Generando estimación…"):
                try:
                    session_id = ensure_session_id()
                    st.session_state.estimation_result = submit_estimation(request, session_id)
                except httpx.TimeoutException:
                    st.error("El servicio no respondió a tiempo. Vuelve a intentarlo.")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        st.session_state.pop("session_id", None)
                    messages = {
                        404: "La sesión ha expirado. Vuelve a enviar el formulario.",
                        422: "El servicio rechazó los datos. Revisa el formulario.",
                        502: "No se pudo obtener una estimación del proveedor.",
                        503: "El servicio de estimaciones no está disponible.",
                        504: "El proveedor no respondió a tiempo. Vuelve a intentarlo.",
                    }
                    st.error(messages.get(exc.response.status_code, "No se pudo obtener la estimación."))
                except httpx.RequestError:
                    st.error("No se pudo conectar con el servicio de estimaciones.")
                except (KeyError, TypeError, ValueError):
                    st.error("El servicio devolvió una respuesta con un formato inesperado.")

    result = st.session_state.get("estimation_result")
    if result is not None:
        st.subheader("Estimación")
        st.markdown(result.text)


if __name__ == "__main__":
    main()
