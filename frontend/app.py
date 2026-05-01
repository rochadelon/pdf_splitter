import os
import sys
import asyncio
import io
import zipfile

import streamlit as st

# Permite importar os serviços do diretório raiz do repositório
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from services.pdf_service import extract_text_and_metadata, split_pdf_by_chapters
from services.nlp_service import identify_chapters

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Semantic PDF Splitter",
    page_icon="📄",
    layout="centered",
)

# ---------------------------------------------------------------------------
# CSS personalizado
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .hero {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        border-radius: 16px;
        padding: 2.5rem 2rem;
        text-align: center;
        margin-bottom: 2rem;
    }
    .hero h1 { color: #e2e8f0; font-size: 2rem; margin: 0; }
    .hero p  { color: #94a3b8; margin: 0.5rem 0 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — Configuração
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚙️ Configuração")
    st.markdown("---")

    api_key_input = st.text_input(
        "🔑 Mistral API Key",
        type="password",
        placeholder="Insira sua chave aqui…",
        help=(
            "Obtenha sua chave em [console.mistral.ai](https://console.mistral.ai/). "
            "Ela não é armazenada — só existe durante a sessão."
        ),
        key="mistral_api_key",
    )

    if api_key_input:
        st.success("✅ Chave configurada")
    else:
        st.warning("⚠️ Insira uma API Key para continuar")

    st.markdown("---")
    st.markdown(
        "<small>Sua chave é usada apenas para chamar a API do Mistral e não é salva.</small>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <h1>📄 Semantic PDF Splitter</h1>
        <p>Divida qualquer PDF em capítulos automaticamente usando <strong>Mistral OCR</strong></p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Upload e processamento
# ---------------------------------------------------------------------------

api_key_ready = bool(st.session_state.get("mistral_api_key", "").strip())

uploaded_file = st.file_uploader(
    "Selecione um arquivo PDF",
    type=["pdf"],
    help="Livros, manuais, teses — qualquer PDF com capítulos.",
    disabled=not api_key_ready,
)

if not api_key_ready:
    st.info("👈 Insira sua **Mistral API Key** na barra lateral para começar.")

if uploaded_file and api_key_ready:
    st.info(f"📎 **{uploaded_file.name}** — {uploaded_file.size / 1024:.1f} KB")

    if st.button("🚀 Processar PDF", use_container_width=True, type="primary"):
        pdf_bytes = uploaded_file.getvalue()
        api_key = st.session_state["mistral_api_key"].strip()

        try:
            # Etapa 1: extração de metadados (local, sem API)
            with st.spinner("📖 Extraindo metadados do PDF…"):
                pages = extract_text_and_metadata(pdf_bytes)

            # Etapa 2: Mistral OCR identifica capítulos
            with st.spinner("🤖 Mistral OCR analisando estrutura do documento…"):
                chapters = asyncio.run(
                    identify_chapters(pages, pdf_bytes=pdf_bytes, api_key=api_key)
                )

            # Etapa 3: split físico e empacotamento em ZIP
            with st.spinner(f"✂️ Dividindo em {len(chapters)} capítulo(s)…"):
                chapter_files = split_pdf_by_chapters(pdf_bytes, chapters)

                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for filename, file_bytes in chapter_files:
                        zf.writestr(filename, file_bytes)
                zip_buffer.seek(0)

            st.success(f"✅ {len(chapters)} capítulo(s) identificado(s) e extraídos!")

            # Lista os capítulos encontrados
            with st.expander("📋 Capítulos encontrados", expanded=True):
                for ch in chapters:
                    st.markdown(
                        f"- **{ch['chapter']}** — páginas {ch['start_page']}–{ch['end_page']}"
                    )

            st.download_button(
                label="📦 Baixar capítulos (.zip)",
                data=zip_buffer.getvalue(),
                file_name=f"{uploaded_file.name.replace('.pdf', '')}_chapters.zip",
                mime="application/zip",
                use_container_width=True,
            )

        except ValueError as exc:
            st.error(f"❌ {exc}")
        except Exception as exc:
            st.error(f"❌ Erro inesperado: {exc}")
            st.exception(exc)

# ---------------------------------------------------------------------------
# Rodapé informativo
# ---------------------------------------------------------------------------

with st.expander("ℹ️ Como funciona?"):
    st.markdown(
        """
        1. **API Key** — Insira sua chave Mistral na barra lateral (só existe na sessão).
        2. **Upload** — Selecione qualquer PDF com estrutura de capítulos.
        3. **Extração** — `PyMuPDF` lê metadados estruturais de cada página.
        4. **Mistral OCR** — O PDF é enviado ao `mistral-ocr-latest`, que lê o layout visual e extrai capítulos em JSON estruturado — inclusive em PDFs escaneados.
        5. **Split** — O PDF é cortado fisicamente preservando imagens e formatação original.
        6. **Download** — Todos os capítulos são entregues em um único arquivo `.zip`.
        """
    )
