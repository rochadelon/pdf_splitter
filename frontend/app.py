"""
app.py — Frontend Streamlit do Semantic PDF Splitter
"""

import time
import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

API_BASE = "http://backend:8000/api"   # nome do serviço Docker Compose
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
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <h1>📄 Semantic PDF Splitter</h1>
        <p>Divida qualquer PDF em capítulos automaticamente usando Inteligência Artificial</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

uploaded_file = st.file_uploader(
    "Selecione um arquivo PDF",
    type=["pdf"],
    help="Livros, manuais, teses — qualquer PDF com capítulos.",
)

if uploaded_file:
    st.info(f"📎 **{uploaded_file.name}** — {uploaded_file.size / 1024:.1f} KB")

    if st.button("🚀 Processar PDF", use_container_width=True, type="primary"):
        # Envia para o backend
        with st.spinner("Enviando arquivo…"):
            try:
                response = httpx.post(
                    f"{API_BASE}/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
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
    "pending":    ("⏳ Aguardando…",          "badge-pending"),
    "extracting": ("📖 Extraindo texto…",      "badge-extracting"),
    "analyzing":  ("🤖 Analisando com IA…",   "badge-analyzing"),
    "splitting":  ("✂️ Dividindo PDF…",        "badge-splitting"),
    "done":       ("✅ Concluído!",             "badge-done"),
    "error":      ("❌ Erro no processamento", "badge-error"),
}

if st.session_state.get("task_id") and not st.session_state.get("done"):
    task_id = st.session_state["task_id"]

    status_placeholder = st.empty()
    progress_bar = st.progress(0)

    while True:
        try:
            resp = httpx.get(f"{API_BASE}/status/{task_id}", timeout=10)
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
        zip_response = httpx.get(f"{API_BASE}/download/{task_id}", timeout=30)
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
        1. **Upload** — O PDF é enviado para o backend via API REST.
        2. **Extração** — `PyMuPDF` lê o texto e os metadados de fonte de cada página.
        3. **Filtro Heurístico** — RegEx e análise de tamanho de fonte identificam candidatos a capítulos.
        4. **Validação IA** — Um LLM (GPT-4o-mini) confirma e extrai o título exato de cada capítulo.
        5. **Split** — O PDF é cortado fisicamente preservando imagens e formatação.
        6. **Download** — Todos os capítulos são entregues em um único arquivo `.zip`.
        """
    )
