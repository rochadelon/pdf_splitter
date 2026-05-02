# Semantic PDF Splitter

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Mistral AI](https://img.shields.io/badge/Mistral_OCR-mistral--ocr--latest-FF7000?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyTDIgN2wxMCA1IDEwLTV6TTIgMTdsOSA1IDktNXYtNWwtOSA1LTktNXoiLz48L3N2Zz4=&logoColor=white)
![PyMuPDF](https://img.shields.io/badge/PyMuPDF-1.24%2B-4CAF50?style=for-the-badge&logo=adobeacrobatreader&logoColor=white)

**Divide qualquer PDF em capítulos automaticamente usando Mistral OCR + IA.**

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://alanspdfsplitter.streamlit.app)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-delonrocha-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/delonrocha/)

</div>

---

## 🚀 Como funciona

```
PDF ──▶ Mistral OCR ──▶ Parser de Headings ──▶ Split físico (PyMuPDF) ──▶ ZIP
              │                  │
              │         Cascata de estratégias:
              │          1. Padrões estritos ("Chapter N", "Part I")
              │          2. Headings H1 únicos
              └──────▶   3. Chat (mistral-large-latest) como fallback
```

1. Upload do PDF via interface Streamlit
2. **Mistral OCR** extrai o texto de cada página em Markdown estruturado
3. Parser detecta capítulos em cascata (padrões → H1 → chat)
4. **PyMuPDF** corta o PDF fisicamente preservando imagens e formatação
5. Capítulos entregues em `.zip` para download

---

## 🛠️ Stack

| Camada | Tecnologia | Função |
|---|---|---|
| 🖥️ Frontend | ![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white) | Interface de upload e download |
| ⚙️ Backend | ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white) | API REST assíncrona |
| 🔍 OCR | ![Mistral AI](https://img.shields.io/badge/Mistral_OCR-FF7000?style=flat&logoColor=white) | Extração de texto e estrutura |
| 🤖 Chat | ![Mistral AI](https://img.shields.io/badge/mistral--large--latest-FF7000?style=flat&logoColor=white) | Validação de capítulos (fallback) |
| 📄 PDF | ![PyMuPDF](https://img.shields.io/badge/PyMuPDF-4CAF50?style=flat&logo=adobeacrobatreader&logoColor=white) | Split físico do PDF |
| 🌐 HTTP | ![HTTPX](https://img.shields.io/badge/httpx-0.27%2B-0075A8?style=flat&logoColor=white) | Chamadas à API Mistral |
| 🐳 Deploy | ![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?style=flat&logo=docker&logoColor=white) | Orquestração de serviços |

---

## 🐳 Deploy com Docker (self-hosted)

```bash
# 1. Configure a chave Mistral (opcional — pode inserir pela interface)
copy .env.example .env

# 2. Suba os serviços
docker compose up --build
```

| Serviço | URL |
|---|---|
| 🎨 Frontend (Streamlit) | http://localhost:8501 |
| ⚙️ Backend API (FastAPI) | http://localhost:8000/docs |

```bash
# Parar
docker compose down
```

---

## ☁️ Deploy no Streamlit Cloud

1. Faça fork do repositório
2. Acesse [share.streamlit.io](https://share.streamlit.io) e conecte o repositório
3. Defina **Main file path** como `frontend/app.py`
4. *(Opcional)* Em **Settings → Secrets**, adicione:
   ```toml
   MISTRAL_API_KEY = "sua-chave-aqui"
   ```
5. Deploy! A chave também pode ser inserida pela barra lateral da interface.

---

## 🔧 Setup Manual (sem Docker)

```bash
cd pdf_splitter
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r frontend/requirements.txt

# Streamlit standalone
streamlit run frontend/app.py
```

---

## 📡 Endpoints da API

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/upload` | Envia o PDF e inicia o processamento assíncrono |
| `GET` | `/api/status/{task_id}` | Verifica o progresso via polling |
| `GET` | `/api/download/{task_id}` | Baixa o ZIP com os capítulos |

---

## 📁 Estrutura

```
pdf_splitter/
├── api/
│   ├── main.py              # Ponto de entrada FastAPI + CORS
│   ├── endpoints.py         # Rotas: upload / status / download
│   └── models.py            # Schemas Pydantic
├── services/
│   ├── pdf_service.py       # PyMuPDF: extração de metadados e split físico
│   ├── nlp_service.py       # Mistral OCR + cascata de detecção de capítulos
│   └── file_service.py      # Empacotamento ZIP e limpeza de temporários
├── frontend/
│   ├── app.py               # Interface Streamlit (standalone)
│   └── requirements.txt     # Dependências do frontend
├── .streamlit/
│   └── config.toml          # Configuração Streamlit Cloud
├── Dockerfile.backend        # Imagem Docker — FastAPI
├── Dockerfile.frontend       # Imagem Docker — Streamlit
├── docker-compose.yml        # Orquestração dos dois serviços
├── requirements.txt          # Dependências do backend
├── .env.example              # Template de variáveis de ambiente
└── .gitignore
```

---

## 🔑 Variáveis de Ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `MISTRAL_API_KEY` | *(vazio)* | Chave da API Mistral — pode ser inserida pela interface |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | Modelo de OCR |
| `MISTRAL_CHAT_MODEL` | `mistral-large-latest` | Modelo de chat (fallback) |
| `API_BASE` | `http://localhost:8000/api` | URL do backend (Streamlit Cloud / Docker) |
