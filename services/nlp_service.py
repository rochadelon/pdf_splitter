"""
nlp_service.py
--------------
Pipeline de identificação de capítulos via API REST do Mistral.
Sem código executável em nível de módulo — seguro para importar em qualquer
versão do Python (3.9+).
"""

import base64
import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Constantes simples (sem instanciação de objetos)
# ---------------------------------------------------------------------------

MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_OCR_MODEL: str = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
MISTRAL_CHAT_MODEL: str = os.getenv("MISTRAL_CHAT_MODEL", "mistral-large-latest")
MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
_REQUEST_TIMEOUT: float = 180.0

# Padrões de capítulo como strings (compilados dentro das funções)
_RAW_PATTERNS = [
    r"(?i)^(capitulo|chapter|parte|part|secao|section|unit|unidade)\s+[\dIVXivx]+",
    r"(?i)^(introducao|introduction|conclusao|conclusion|referencias|references|abstract|resumo|sumario|prefacio|foreword)\s*$",
    r"^[\d]+[.)] [A-Z\w].{2,60}$",
]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_chapter_patterns():
    """Compila os padrões de capítulo (lazy, dentro de função)."""
    return [re.compile(p) for p in _RAW_PATTERNS]


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
    """Faz POST com httpx importado localmente (evita falha no import do módulo)."""
    import httpx  # import local — não falha ao carregar o módulo
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        return client.post(url, headers=headers, json=payload)


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
    resp = _http_post(
        MISTRAL_BASE_URL + "/ocr",
        _auth_headers(api_key),
        payload,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            "Erro na API de OCR (HTTP %d): %s" % (resp.status_code, resp.text[:400])
        )
    return resp.json().get("pages", [])


# ---------------------------------------------------------------------------
# Etapa 2: Parsing de headings Markdown
# ---------------------------------------------------------------------------

def _extract_heading_candidates(ocr_pages):
    patterns = _get_chapter_patterns()
    candidates = []
    seen = set()

    for page in ocr_pages:
        page_num = page.get("index", 0) + 1
        markdown = page.get("markdown", "")

        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) < 3:
                continue

            title = None
            level = 99

            if stripped.startswith("# "):
                title = stripped[2:].strip()
                level = 1
            elif stripped.startswith("## "):
                title = stripped[3:].strip()
                level = 2
            elif stripped.startswith("### "):
                candidate = stripped[4:].strip()
                if any(p.search(candidate) for p in patterns):
                    title = candidate
                    level = 3
            else:
                if any(p.search(stripped) for p in patterns):
                    title = stripped
                    level = 2

            if title and len(title) >= 3:
                title = re.sub(r"[*_`#]+", "", title).strip()
                key = "%d:%s" % (page_num, title.lower())
                if key not in seen:
                    seen.add(key)
                    candidates.append({
                        "title": title,
                        "start_page": page_num,
                        "level": level,
                    })

    return candidates


def _filter_top_level(candidates):
    if not candidates:
        return []
    min_level = min(c["level"] for c in candidates)
    return [c for c in candidates if c["level"] <= min_level + 1]


# ---------------------------------------------------------------------------
# Etapa 3b: Chat (fallback)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Você é um especialista em análise de estrutura de documentos PDF.\n"
    "Receberá candidatos a títulos de capítulos extraídos por OCR.\n"
    "Identifique quais são REALMENTE capítulos ou seções principais.\n\n"
    "Responda APENAS com JSON válido no formato:\n"
    '{"chapters": [{"title": "Título", "start_page": N}, ...]}\n\n'
    "Critérios: títulos curtos e descritivos (< 80 chars), nível superior apenas.\n"
    "Se nenhum for capítulo real, retorne: {\"chapters\": []}"
)


def _validate_via_chat(candidates, api_key):
    lines = ['Pagina %d: "%s"' % (c["start_page"], c["title"]) for c in candidates]
    user_content = "Candidatos extraídos do PDF:\n\n" + "\n".join(lines)

    payload = {
        "model": MISTRAL_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 2000,
    }
    resp = _http_post(
        MISTRAL_BASE_URL + "/chat/completions",
        _auth_headers(api_key),
        payload,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            "Erro na API de Chat (HTTP %d): %s" % (resp.status_code, resp.text[:400])
        )
    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(raw).get("chapters", [])
    except json.JSONDecodeError as exc:
        raise ValueError("Resposta inválida do modelo: " + raw[:200]) from exc


def _fallback_candidates(ocr_pages):
    candidates = []
    for page in ocr_pages:
        page_num = page.get("index", 0) + 1
        markdown = page.get("markdown", "")
        lines = [l.strip() for l in markdown.splitlines() if l.strip()][:3]
        for line in lines:
            if 3 < len(line) < 100:
                candidates.append({"title": line, "start_page": page_num, "level": 5})
    return candidates[:50]


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def run_ocr_analysis(pdf_bytes, api_key=None):
    """
    Executa OCR e parsing de headings.
    Retorna dict com resultados intermediários para diagnóstico.
    """
    key = _resolve_key(api_key)
    ocr_pages = _run_ocr(pdf_bytes, key)
    candidates = _extract_heading_candidates(ocr_pages)
    top = _filter_top_level(candidates)
    return {
        "ocr_pages": ocr_pages,
        "candidates": candidates,
        "top_candidates": top,
    }


async def identify_chapters(pages, pdf_bytes=None, api_key=None):
    """
    Pipeline completo de identificação de capítulos.

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
        raise ValueError("OCR não retornou páginas. PDF pode estar corrompido.")

    # Etapa 2: parsing direto
    candidates = _extract_heading_candidates(ocr_pages)
    top = _filter_top_level(candidates)

    # Etapa 3a: headings suficientes → usa direto
    raw_chapters = []
    if len(top) >= 2:
        raw_chapters = [{"title": c["title"], "start_page": c["start_page"]} for c in top]
    else:
        # Etapa 3b: fallback para chat
        chat_input = candidates if candidates else _fallback_candidates(ocr_pages)
        raw_chapters = _validate_via_chat(chat_input, key)

    if not raw_chapters:
        raise ValueError(
            "Nenhum capítulo identificado.\n"
            "Verifique se o PDF tem títulos visíveis e não está protegido por senha."
        )

    # Monta resultado com end_page calculado
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
