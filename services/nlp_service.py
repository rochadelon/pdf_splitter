"""
nlp_service.py
--------------
Pipeline de identificação de capítulos de nível superior via Mistral OCR.

Estratégia em cascata (para cada nível falhar, tenta o próximo):
  1. Padrões estritos de capítulo ("Chapter N", "Part I", "Appendix A")
  2. Headings H1 únicos (sem repetição do título do documento)
  3. Chat (mistral-large-latest) com prompt cirúrgico
"""

import base64
import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_OCR_MODEL: str = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
MISTRAL_CHAT_MODEL: str = os.getenv("MISTRAL_CHAT_MODEL", "mistral-large-latest")
MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
_REQUEST_TIMEOUT: float = 180.0

# Padrões que indicam CAPÍTULOS de nível superior (internacionais)
_STRICT_CHAPTER_PATTERNS = [
    # "Chapter 1", "Chapter 1.", "Capítulo 2"
    r"^(chapter|capítulo|capitulo|chapitre|kapitel)\s*[\d]+",
    # "Part I", "Part 1", "Parte II", "Part Two"
    r"^(part|parte)\s+(I{1,4}V?|V?I{0,3}|\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    # "Appendix A", "Appendix 1", "Apêndice B"
    r"^(appendix|apêndice|apendice|anexo)\s+[a-z\d]",
    # Seções nomeadas comuns (início de documento)
    r"^(preface|prefácio|foreword|introduction|introdução|conclusion|conclusão|acknowledgments|agradecimentos|bibliography|references|referências|index|índice|glossary|glossário|abstract|resumo|summary|sumário)\s*$",
]


def _get_strict_patterns():
    return [re.compile(p, re.IGNORECASE) for p in _STRICT_CHAPTER_PATTERNS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_key(api_key):
    key = api_key or MISTRAL_API_KEY
    if not key:
        raise EnvironmentError(
            "Nenhuma MISTRAL_API_KEY configurada. "
            "Insira sua chave na barra lateral."
        )
    return key


def _auth_headers(api_key):
    return {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }


def _http_post(url, headers, payload):
    import httpx
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        return client.post(url, headers=headers, json=payload)


def _clean_title(raw):
    """Remove marcações Markdown residuais e espaços extras."""
    cleaned = re.sub(r"[*_`#\\[\\]]+", "", raw)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Etapa 1: OCR
# ---------------------------------------------------------------------------

def _run_ocr(pdf_bytes, api_key):
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    payload = {
        "model": MISTRAL_OCR_MODEL,
        "document": {
            "type": "document_url",
            "document_url": "data:application/pdf;base64," + b64,
        },
    }
    resp = _http_post(MISTRAL_BASE_URL + "/ocr", _auth_headers(api_key), payload)
    if resp.status_code != 200:
        raise RuntimeError("Erro OCR (HTTP %d): %s" % (resp.status_code, resp.text[:400]))
    return resp.json().get("pages", [])


# ---------------------------------------------------------------------------
# Etapa 2: Extração de headings do Markdown OCR
# ---------------------------------------------------------------------------

def _extract_all_headings(ocr_pages):
    """
    Extrai TODOS os headings Markdown (H1-H4) com página e nível.
    Retorna lista de {"title": str, "start_page": int, "level": int}.
    """
    headings = []
    seen_keys = set()

    for page in ocr_pages:
        page_num = page.get("index", 0) + 1
        markdown = page.get("markdown", "")

        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            level = None
            raw_title = None

            if stripped.startswith("#### "):
                level, raw_title = 4, stripped[5:]
            elif stripped.startswith("### "):
                level, raw_title = 3, stripped[4:]
            elif stripped.startswith("## "):
                level, raw_title = 2, stripped[3:]
            elif stripped.startswith("# "):
                level, raw_title = 1, stripped[2:]

            if level is None or not raw_title:
                continue

            title = _clean_title(raw_title)
            if len(title) < 2:
                continue

            # Deduplica por (título normalizado, nível) — mantém apenas a primeira ocorrência
            dedup_key = (title.lower(), level)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            headings.append({"title": title, "start_page": page_num, "level": level})

    return headings


# ---------------------------------------------------------------------------
# Estratégia 1: padrões estritos de capítulo
# ---------------------------------------------------------------------------

def _find_by_strict_patterns(headings):
    """
    Filtra headings que batem com padrões explícitos de capítulo de livro.
    Retorna lista ordenada por página.
    """
    patterns = _get_strict_patterns()
    matched = []
    for h in headings:
        if any(p.search(h["title"]) for p in patterns):
            matched.append(h)
    return matched


# ---------------------------------------------------------------------------
# Estratégia 2: somente H1 únicos (sem repetir o título do documento)
# ---------------------------------------------------------------------------

def _find_h1_only(headings, min_count=2):
    """
    Retorna headings de nível H1. Se houver apenas 1 H1 (geralmente o título
    do documento), tenta H2. Exige min_count para aceitar.
    """
    for level in (1, 2):
        candidates = [h for h in headings if h["level"] == level]
        if len(candidates) >= min_count:
            return candidates
    return []


# ---------------------------------------------------------------------------
# Estratégia 3: fallback via chat
# ---------------------------------------------------------------------------

_CHAT_SYSTEM = """Você é um especialista em estrutura de documentos e livros técnicos.

Receberá headings extraídos via OCR de um PDF, com nível Markdown (H1-H4) e página.
Sua tarefa: identificar SOMENTE os capítulos e partes de NÍVEL SUPERIOR do documento.

Regras ESTRITAS:
- Inclua: "Chapter N", "Part N", "Appendix X", "Introduction", "Conclusion", "Preface", "Acknowledgments"
- NÃO inclua: subseções (1.1, 1.2), títulos de tabelas/figuras, sidebars, caixas de texto, itens numerados dentro de capítulos
- O título do livro/documento NÃO é um capítulo — exclua-o
- Se um heading se repetir, inclua apenas na primeira ocorrência

Responda APENAS com JSON válido, sem explicações:
{"chapters": [{"title": "Título exato", "start_page": N}, ...]}

Se não houver capítulos identificáveis, retorne: {"chapters": []}"""


def _find_via_chat(headings, api_key):
    """Envia a lista compacta de headings ao chat para filtragem inteligente."""
    if not headings:
        return []

    lines = ["H%d | Pág %d | %s" % (h["level"], h["start_page"], h["title"])
             for h in headings]
    user_content = "Headings extraídos do PDF:\n\n" + "\n".join(lines)

    payload = {
        "model": MISTRAL_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": _CHAT_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 2000,
    }
    resp = _http_post(MISTRAL_BASE_URL + "/chat/completions", _auth_headers(api_key), payload)
    if resp.status_code != 200:
        raise RuntimeError("Erro Chat (HTTP %d): %s" % (resp.status_code, resp.text[:400]))

    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(raw).get("chapters", [])
    except json.JSONDecodeError as exc:
        raise ValueError("Resposta inválida do modelo: " + raw[:200]) from exc


# ---------------------------------------------------------------------------
# API pública — diagnóstico
# ---------------------------------------------------------------------------

def run_ocr_analysis(pdf_bytes, api_key=None):
    """
    Executa OCR e extrai headings para diagnóstico.
    Retorna dict com resultados intermediários.
    """
    key = _resolve_key(api_key)
    ocr_pages = _run_ocr(pdf_bytes, key)
    headings = _extract_all_headings(ocr_pages)
    strict = _find_by_strict_patterns(headings)
    h1_only = _find_h1_only(headings)
    return {
        "ocr_pages": ocr_pages,
        "candidates": headings,
        "top_candidates": strict if strict else h1_only,
        "strategy": "strict_patterns" if strict else ("h1_only" if h1_only else "chat"),
    }


# ---------------------------------------------------------------------------
# API pública — identificação de capítulos
# ---------------------------------------------------------------------------

async def identify_chapters(pages, pdf_bytes=None, api_key=None):
    """
    Identifica capítulos do PDF em cascata de estratégias.

    Returns:
        [{"chapter": str, "start_page": int, "end_page": int}, ...]
    """
    if pdf_bytes is None:
        raise ValueError("pdf_bytes é obrigatório.")

    key = _resolve_key(api_key)
    total_pages = pages[-1]["page_number"] if pages else 1

    # Etapa 1: OCR
    ocr_pages = _run_ocr(pdf_bytes, key)
    if not ocr_pages:
        raise ValueError("OCR não retornou páginas.")

    headings = _extract_all_headings(ocr_pages)

    # Cascata de estratégias
    raw_chapters = []
    strategy_used = "none"

    # Estratégia 1: padrões estritos ("Chapter N", "Part I"...)
    strict = _find_by_strict_patterns(headings)
    if strict:
        raw_chapters = [{"title": h["title"], "start_page": h["start_page"]} for h in strict]
        strategy_used = "strict_patterns"

    # Estratégia 2: H1 somente (sem repetição)
    if not raw_chapters:
        h1 = _find_h1_only(headings, min_count=2)
        if h1:
            raw_chapters = [{"title": h["title"], "start_page": h["start_page"]} for h in h1]
            strategy_used = "h1_only"

    # Estratégia 3: chat com lista de headings compacta
    if not raw_chapters:
        raw_chapters = _find_via_chat(headings, key)
        strategy_used = "chat"

    if not raw_chapters:
        raise ValueError(
            "Nenhum capítulo identificado.\n"
            "Verifique se o PDF tem títulos visíveis (ex: 'Chapter 1', 'Capítulo 1') "
            "e não está protegido por senha."
        )

    # Calcula end_page
    result = []
    for i, ch in enumerate(raw_chapters):
        start = max(1, int(ch.get("start_page", 1)))
        if i + 1 < len(raw_chapters):
            end = max(start, int(raw_chapters[i + 1].get("start_page", start + 1)) - 1)
        else:
            end = total_pages
        result.append({
            "chapter": ch.get("title", "Capitulo %d" % (i + 1)),
            "start_page": start,
            "end_page": end,
        })

    return result
