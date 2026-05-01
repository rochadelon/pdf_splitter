# Semantic PDF Splitter

Divide automaticamente um PDF em capítulos usando **análise semântica com IA**.

## Como funciona

1. Usuário faz upload do PDF via API
2. O sistema extrai texto e metadados (tamanho de fonte) com **PyMuPDF**
3. Um **filtro heurístico** (RegEx + fonte) pré-seleciona candidatos a capítulos
4. O **LLM** (GPT-4o-mini por padrão) valida e extrai os títulos exatos
5. O PDF é cortado fisicamente nos intervalos identificados
6. O resultado é entregue como um arquivo `.zip` com os PDFs renomeados

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | FastAPI + Uvicorn |
| PDF | PyMuPDF (fitz) |
| IA | OpenAI GPT-4o-mini |
| Empacotamento | zipfile (stdlib) |

## 🐳 Deploy com Docker (recomendado)

```bash
# 1. Copie e configure o arquivo de ambiente
copy .env.example .env
# Edite .env e insira sua OPENAI_API_KEY

# 2. Suba os dois serviços com um comando
docker compose up --build
```

| Serviço | URL |
|---|---|
| Frontend (Streamlit) | http://localhost:8501 |
| Backend API (FastAPI) | http://localhost:8000/docs |

Para parar: `docker compose down`

---

## Setup Manual (sem Docker)

```bash
# 1. Clone e entre na pasta
cd pdf_splitter

# 2. Crie e ative o virtualenv
python -m venv .venv
.venv\Scripts\activate   # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure as variáveis de ambiente
copy .env.example .env
# Edite .env e insira sua OPENAI_API_KEY

# 5. Suba o servidor
uvicorn api.main:app --reload
```

A API estará disponível em `http://localhost:8000`.
Documentação interativa: `http://localhost:8000/docs`

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/upload` | Envia o PDF e inicia o processamento |
| `GET` | `/api/status/{task_id}` | Verifica o progresso (polling) |
| `GET` | `/api/download/{task_id}` | Baixa o ZIP final |

## Estrutura

```
pdf_splitter/
├── api/
│   ├── main.py              # Ponto de entrada do FastAPI
│   ├── endpoints.py         # Rotas da API
│   └── models.py            # Schemas Pydantic
├── services/
│   ├── pdf_service.py       # PyMuPDF: extração e split
│   ├── nlp_service.py       # LLM: análise semântica
│   └── file_service.py      # ZIP e arquivos temporários
├── frontend/
│   ├── app.py               # Interface Streamlit
│   └── requirements.txt     # Deps exclusivas do frontend
├── temp/                    # PDFs/ZIPs temporários (auto-gerado)
├── Dockerfile.backend       # Imagem Docker do FastAPI
├── Dockerfile.frontend      # Imagem Docker do Streamlit
├── docker-compose.yml       # Orquestração dos dois serviços
├── requirements.txt
├── .env.example
└── .gitignore
```
