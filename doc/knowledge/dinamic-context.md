Camino A — Multimodal directo: el PDF viaja al LLM
Los proveedores grandes han añadido soporte nativo para PDFs en los últimos meses. Le pasas el archivo a la API y el modelo extrae texto, interpreta diagramas y razona sobre el contenido visual sin que tú tengas que hacer ningún preprocesado.

En Anthropic, el patrón canónico es subir el archivo a través de la Files API y luego referenciarlo en el bloque de contenido del mensaje:

python

import anthropic

client = anthropic.Anthropic()

with open("specification.pdf", "rb") as f:
    uploaded = client.beta.files.upload(
        file=("specification.pdf", f, "application/pdf"),
    )

response = client.beta.messages.create(
    model="claude-opus-4-7",
    max_tokens=2048,
    betas=["files-api-2025-04-14"],
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "file", "file_id": uploaded.id},
                },
                {
                    "type": "text",
                    "text": "Use this technical specification as additional context when producing the estimate.",
                },
            ],
        }
    ],
)
OpenAI ofrece el mismo patrón en la Responses API, con el archivo subido vía la Files API y referenciado en el input del mensaje. La diferencia conceptual con Anthropic es mínima; la diferencia de SDK la encapsula tu wrapper de proveedores de la sesión 03.

Las ventajas son claras. Cero código de extracción. El modelo ve los diagramas y los interpreta — un diagrama de arquitectura ASCII, un gráfico de Gantt, una captura de un wireframe — y lo incorpora al razonamiento. La latencia de carga del archivo se paga una sola vez (la Files API mantiene el archivo durante la conversación, sólo subes una vez) y el resto de turnos referencian el file_id.

Las desventajas son menos obvias pero importantes. Estás acoplado al proveedor multimodal: cambiar de OpenAI a un modelo open-source local que no soporte PDF nativo te obliga a cambiar la arquitectura. El consumo de tokens es mayor que el de un texto extraído equivalente, porque el modelo internamente tokeniza tanto el contenido textual como una representación visual de cada página. Y tienes menos control sobre qué partes del documento entran al contexto: o todo o nada.

Camino B — Extracción local: solo el texto viaja al LLM
El otro camino es extraer el contenido del documento en tu servicio IA, antes de la llamada al LLM, y enviar solamente texto. Para PDFs nativos de texto, pypdf o PyMuPDF resuelven el caso simple en pocas líneas; para PDFs escaneados o con layout complejo, librerías como Docling o MarkItDown producen markdown estructurado que conserva tablas, encabezados y jerarquía. Para Word existe python-docx.

python

from pypdf import PdfReader
from io import BytesIO

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    parts = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        parts.append(f"--- Page {index} ---\\n{text}")
    return "\\n\\n".join(parts)
Una vez tienes el texto, lo concatenas al prompt con un delimitador claro que el LLM pueda reconocer:

python

attachments_block = "\\n\\n".join(
    f"<attachment filename='{att.filename}'>\\n{extract_text_from_pdf(att.bytes)}\\n</attachment>"
    for att in attachments
)

user_prompt = f"""
<transcript>
{transcript}
</transcript>

<attachments>
{attachments_block}
</attachments>

Produce a software estimate based on the transcript. Use the attachments as additional context.
"""
Las ventajas se invierten respecto al camino A. Eres independiente del proveedor: tu wrapper sigue funcionando con cualquier modelo, multimodal o no. Tienes control fino sobre qué pasa al contexto: puedes filtrar páginas, redactar secciones sensibles, recortar a un budget de tokens. Y, crucialmente, estás preparando el terreno para RAG: la lógica de extracción de texto que escribes hoy es exactamente la primera pieza del pipeline de chunking que vas a montar en el módulo 3.

Las desventajas son el código que tienes que mantener (extracción para PDF, extracción para Word, extracción para imágenes…) y la pérdida de información visual: si el documento contiene un diagrama de arquitectura crítico, una extracción de texto plano no lo capta. Hay un middle ground —Docling, MarkItDown y LlamaParse usan internamente modelos multimodales para producir markdown enriquecido— pero entonces vuelves a depender de servicios externos.