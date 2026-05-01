
### 1. Visão Geral do Projeto
*   **Nome Sugerido:** Semantic PDF Splitter
*   **Objetivo:** Receber um arquivo PDF (ex: livros, manuais, teses), ler seu conteúdo, identificar as quebras de capítulos ou seções de forma semântica, dividir o documento físico nessas fronteiras, renomear os novos arquivos com base no título do capítulo e devolvê-los ao usuário (geralmente em um arquivo `.zip`).

### 2. Stack Tecnológico Recomendado
Como o projeto envolve forte processamento de texto e IA/NLP, **Python** é a escolha ideal para o backend.

*   **Frontend:** Streamlit (para um protótipo rápido) ou React/Next.js (para uma aplicação em produção).
*   **Backend:** FastAPI (rápido, assíncrono e ótimo para lidar com uploads e processamento pesado).
*   **Manipulação de PDF:** 
    *   `PyMuPDF` (também conhecido como *fitz*): Excelente para extração de texto preservando a localização na página e para realizar o corte (split) final mantendo a formatação e imagens originais.
    *   *Opcional (OCR):* `Tesseract` (via `pytesseract`) caso precise lidar com PDFs escaneados (sem texto selecionável).
*   **Motor Semântico (NLP):**
    *   **LLMs via API** (OpenAI `gpt-3.5-turbo`/`gpt-4o-mini` ou Anthropic `Claude Haiku`): Para ler trechos de texto e classificar se representam o início de um novo capítulo, além de extrair o título exato para renomear o arquivo.
    *   **Alternativa Local:** Modelos de embeddings e extração usando `spaCy` ou modelos locais rodando no `Ollama` (ex: Llama 3) para reduzir custos.

### 3. Pipeline de Processamento (Passo a Passo)

#### Etapa 1: Ingestão (Upload)
1. O usuário faz o upload do arquivo via interface.
2. O backend recebe o PDF, salva em um diretório temporário ou na memória e valida o arquivo (verifica se não está corrompido ou protegido por senha).

#### Etapa 2: Extração e Pré-processamento
1. O sistema lê o PDF página por página usando `PyMuPDF`.
2. Extrai o texto cru de cada página, juntamente com metadados estruturais (ex: tamanho da fonte). *Dica: Títulos de capítulos geralmente têm fontes maiores ou estão em negrito.*
3. Cria um mapeamento de "Texto -> Número da Página".

#### Etapa 3: Análise Semântica (O Core do Projeto)
Processar o PDF inteiro de uma vez em um LLM é custoso e ineficiente. A abordagem ideal é um funil em duas etapas:
1. **Filtro Heurístico (Rápido):** Um script busca possíveis candidatos a títulos de capítulos usando RegEx (ex: "Capítulo [0-9]+", "Introdução") e análise de tamanho de fonte (linhas curtas com fontes maiores que a média do texto).
2. **Validação Semântica (IA):** Envia as páginas candidatas (ou trechos em torno delas) para o LLM com o prompt: *"Este texto representa o início de um novo capítulo? Se sim, extraia o título principal."*
3. O resultado é um dicionário ou JSON contendo: `[{"capitulo": "1 - A Origem", "pagina_inicio": 12, "pagina_fim": 34}, ...]`

#### Etapa 4: Divisão Física do PDF (Split)
1. Usando o mapeamento gerado na etapa anterior, o script usa o `PyMuPDF` para instanciar novos arquivos PDF em branco.
2. Copia as páginas do PDF original para os novos PDFs com base nos intervalos (`pagina_inicio` até `pagina_fim`). *Isso garante que imagens, tabelas e layouts originais sejam preservados perfeitamente.*

#### Etapa 5: Renomeação e Empacotamento
1. Os arquivos gerados são salvos com os títulos extraídos pela IA. Exemplo: `01_A_Origem.pdf`, `02_O_Desenvolvimento.pdf`.
2. O sistema compacta todos os arquivos gerados em um único arquivo `.zip`.
3. O arquivo final é enviado como resposta para o frontend para download pelo usuário.

---

### 4. Estrutura de Diretórios (Backend - FastAPI)

```text
/semantic-pdf-splitter
│
├── /api
│   ├── main.py              # Ponto de entrada do FastAPI
│   ├── endpoints.py         # Rotas de upload e download
│   └── models.py            # Esquemas de dados (Pydantic)
│
├── /services
│   ├── pdf_service.py       # Lógica do PyMuPDF (extração de texto e split)
│   ├── nlp_service.py       # Integração com LLM para análise semântica
│   └── file_service.py      # Manipulação de arquivos temporários e geração de ZIP
│
├── /temp                    # Pasta volátil para armazenar uploads/downloads (excluídos após o uso)
├── requirements.txt
└── .env                     # Chaves de API (ex: OPENAI_API_KEY)
```

### 5. Desafios e Soluções Antecipadas

*   **PDFs Escaneados (Imagens):** Se o PDF não tiver camada de texto, a extração retornará vazia. **Solução:** Implementar uma checagem inicial; se a extração render `< 50` caracteres por página, alertar o usuário ou acionar um OCR (Tesseract) antes da análise.
*   **Falsos Positivos:** Identificar um título de capítulo citado no meio de um parágrafo como uma quebra. **Solução:** O prompt do LLM deve receber o contexto estrutural (ex: informar se o texto estava isolado na página ou acompanhado de numeração).
*   **Tempo de Resposta (Timeout):** PDFs de 500 páginas podem demorar minutos para serem processados. **Solução:** Implementar processamento assíncrono. Em vez de o usuário esperar a barra de carregamento na mesma requisição (que pode dar erro de *timeout*), o sistema retorna um `Task ID` e o frontend faz *polling* (verifica o status a cada 5 segundos) até que o arquivo `.zip` esteja pronto.