import os
import time
import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

# Em Docker Compose o nome de serviço é resolvido automaticamente.
# No Streamlit Cloud defina a secret/env API_BASE com a URL pública do backend.
# Fallback para localhost facilita o desenvolvimento sem Docker.
_DEFAULT_API_BASE = os.getenv("API_BASE", "http://localhost:8000/api")
POLL_INTERVAL = 4  # segundos entre verificações de status

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

    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-pending   { background:#374151; color:#d1d5db; }
    .badge-extracting{ background:#1e3a5f; color:#93c5fd; }
    .badge-analyzing { background:#3b2063; color:#c4b5fd; }
    .badge-splitting { background:#1e4d3b; color:#6ee7b7; }
    .badge-done      { background:#166534; color:#bbf7d0; }
    .badge-error     { background:#7f1d1d; color:#fca5a5; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — Configuração da API Key
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚙️ Configuração")
    st.markdown("---")

    api_key_input = st.text_input(
        "🔑 Mistral API Key",
        type="password",
        placeholder="Insira sua chave aqui…",
        help=(
            "Obtenha sua chave gratuita em [console.mistral.ai](https://console.mistral.ai/). "
            "Ela não é armazenada — só existe durante a sessão."
        ),
        key="mistral_api_key",
    )

    if api_key_input:
        st.success("✅ Chave configurada")
    else:
        st.warning("⚠️ Insira uma API Key para continuar")

    st.markdown("---")

    backend_url = st.text_input(
        "🌐 URL do Backend",
        value=_DEFAULT_API_BASE,
        placeholder="http://localhost:8000/api",
        help=(
            "URL base da API FastAPI. Útil ao rodar sem Docker ou no Streamlit Cloud. "
            "No Docker Compose esse valor é preenchido automaticamente."
        ),
        key="api_base",
    )

    st.markdown(
        "<small>A chave é enviada apenas ao seu próprio backend e não é armazenada.</small>",
        unsafe_allow_html=True,
    )


def _get_headers() -> dict:
    """Retorna os headers HTTP incluindo a API key se fornecida."""
    key = st.session_state.get("mistral_api_key", "").strip()
    if key:
        return {"X-Mistral-Api-Key": key}
    return {}


def _get_api_base() -> str:
    """Retorna a URL base da API lida do campo da sidebar."""
    return st.session_state.get("api_base", _DEFAULT_API_BASE).rstrip("/")


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
# Upload
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

if uploaded_file:
    st.info(f"📎 **{uploaded_file.name}** — {uploaded_file.size / 1024:.1f} KB")

    if st.button("🚀 Processar PDF", use_container_width=True, type="primary"):
        with st.spinner("Enviando arquivo…"):
            try:
                response = httpx.post(
                    f"{_get_api_base()}/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
                    headers=_get_headers(),
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                st.session_state["task_id"] = data["task_id"]
                st.session_state["done"] = False
            except httpx.HTTPError as exc:
                st.error(f"Erro ao enviar arquivo: {exc}")
                st.stop()

# ---------------------------------------------------------------------------
# Polling de status
# ---------------------------------------------------------------------------

STATUS_LABELS = {
    "pending":    ("⏳ Aguardando…",           "badge-pending"),
    "extracting": ("📖 Extraindo metadados…",   "badge-extracting"),
    "analyzing":  ("🤖 Mistral OCR em ação…",  "badge-analyzing"),
    "splitting":  ("✂️ Dividindo PDF…",         "badge-splitting"),
    "done":       ("✅ Concluído!",              "badge-done"),
    "error":      ("❌ Erro no processamento",  "badge-error"),
}

if st.session_state.get("task_id") and not st.session_state.get("done"):
    task_id = st.session_state["task_id"]

    status_placeholder = st.empty()
    progress_bar = st.progress(0)

    while True:
        try:
            resp = httpx.get(f"{_get_api_base()}/status/{task_id}", timeout=10)
            resp.raise_for_status()
            task = resp.json()
        except httpx.HTTPError as exc:
            st.error(f"Erro ao verificar status: {exc}")
            break

        status = task.get("status", "pending")
        progress = task.get("progress", 0)
        label, badge_cls = STATUS_LABELS.get(status, ("Desconhecido", "badge-pending"))

        progress_bar.progress(progress / 100)
        status_placeholder.markdown(
            f'<span class="status-badge {badge_cls}">{label}</span>',
            unsafe_allow_html=True,
        )

        if status == "done":
            st.session_state["done"] = True
            break
        if status == "error":
            st.error(f"Erro: {task.get('error', 'Desconhecido')}")
            break

        time.sleep(POLL_INTERVAL)
        st.rerun()

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

if st.session_state.get("done"):
    task_id = st.session_state["task_id"]
    st.success("✅ Seus capítulos estão prontos!")

    try:
        zip_response = httpx.get(f"{_get_api_base()}/download/{task_id}", timeout=30)
        zip_response.raise_for_status()
        st.download_button(
            label="📦 Baixar capítulos (.zip)",
            data=zip_response.content,
            file_name=f"chapters_{task_id[:8]}.zip",
            mime="application/zip",
            use_container_width=True,
        )
    except httpx.HTTPError as exc:
        st.error(f"Erro ao preparar download: {exc}")

    if st.button("🔄 Processar outro PDF", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Rodapé informativo
# ---------------------------------------------------------------------------

with st.expander("ℹ️ Como funciona?"):
    st.markdown(
        """
        1. **API Key** — Insira sua chave Mistral na barra lateral (só existe na sessão, nunca é salva).
        2. **Upload** — O PDF é enviado para o backend via API REST.
        3. **Extração** — `PyMuPDF` lê metadados estruturais de cada página (total de páginas).
        4. **Mistral OCR** — O PDF completo é enviado ao modelo `mistral-ocr-latest`, que lê o layout visual e o texto nativamente — inclusive em PDFs escaneados.
        5. **Schema estruturado** — O modelo retorna os capítulos em JSON validado (título + página de início) sem necessidade de pós-processamento.
        6. **Split** — O PDF é cortado fisicamente com `PyMuPDF`, preservando imagens e formatação.
        7. **Download** — Todos os capítulos são entregues em um único arquivo `.zip`.
        """
    )
