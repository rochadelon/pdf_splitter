"""
nlp_service.py
--------------
Pipeline robusto de identificação de capítulos:

  Etapa 1 — OCR: Mistral OCR extrai cada página em Markdown estruturado.
  Etapa 2 — Parsing: extrai headings Markdown (#, ##) de cada página.
  Etapa 3a — Direto: se headings suficientes → usa-os como capítulos.
  Etapa 3b — Chat: envia lista compacta de candidatos ao modelo de chat
              para confirmar e limpar os títulos (apenas se necessário).
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
MISTRAL_CHAT_MODEL = os.getenv("MISTRAL_CHAT_MODEL", "mistral-large-latest")
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

_TIMEOUT = httpx.Timeout(180.0)

# Padrões que indicam início de capítulo no texto
_CHAPTER_PATTERNS = [
    re.compile(r"(?i)^(cap[íi]tulo|chapter|parte|part|seção|section|unit|unidade)\s+[\dIVXivx]+"),
    re.compile(r"(?i)^(introdução|introduction|conclusão|conclusion|referências|references|abstract|resumo|sumário|prefácio|foreword)\s*$"),
    re.compile(r"^[\d]+[\.\)]\s+[A-ZÁÉÍÓÚÀÃÕ\w].{2,60}$"),
]


def _resolve_key(api_key: str | None) -> str:
    key = api_key or MISTRAL_API_KEY
    if not key:
        raise EnvironmentError(
            "Nenhuma MISTRAL_API_KEY configurada. "
            "Insira sua chave na barra lateral."
        )
    return key


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Etapa 1: OCR
# ---------------------------------------------------------------------------

def _run_ocr(pdf_bytes: bytes, api_key: str) -> list[dict[str, Any]]:
    """Chama /v1/ocr e retorna lista de páginas com markdown."""
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "model": MISTRAL_OCR_MODEL,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{b64}",
        },
    }

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            f"{MISTRAL_BASE_URL}/ocr",
            headers=_auth_headers(api_key),
            json=payload,
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Erro na API de OCR (HTTP {resp.status_code}): {resp.text[:500]}"
        )

    return resp.json().get("pages", [])


# ---------------------------------------------------------------------------
# Etapa 2: Parsing de headings a partir do Markdown do OCR
# ---------------------------------------------------------------------------

def _extract_heading_candidates(ocr_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Percorre o markdown de cada página e extrai linhas que são candidatos
    a capítulo, com base em:
      - Headings Markdown: linhas que começam com # ou ##
      - Padrões heurísticos: "Capítulo N", "1. Título", etc.

    Retorna lista de {"title": str, "start_page": int, "level": int}
    ordenada por página.
    """
    candidates: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for page in ocr_pages:
        page_num = page.get("index", 0) + 1  # OCR usa 0-indexed
        markdown = page.get("markdown", "")

        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) < 3:
                continue

            title: str | None = None
            level = 99  # menor número = maior importância

            # H1 Markdown
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                level = 1
            # H2 Markdown
            elif stripped.startswith("## "):
                title = stripped[3:].strip()
                level = 2
            # H3 Markdown que combina com padrões de capítulo
            elif stripped.startswith("### "):
                candidate = stripped[4:].strip()
                if any(p.search(candidate) for p in _CHAPTER_PATTERNS):
                    title = candidate
                    level = 3
            # Texto plano que combina com padrões heurísticos
            else:
                if any(p.search(stripped) for p in _CHAPTER_PATTERNS):
                    title = stripped
                    level = 2

            if title and len(title) >= 3:
                # Normaliza: remove marcações residuais de Markdown
                title = re.sub(r"[*_`#]+", "", title).strip()
                # Evita duplicatas na mesma página
                key = f"{page_num}:{title.lower()}"
                if key not in seen_titles:
                    seen_titles.add(key)
                    candidates.append({
                        "title": title,
                        "start_page": page_num,
                        "level": level,
                    })

    return candidates


def _filter_top_level(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filtra apenas os candidatos de nível mais alto encontrado.
    Ex: se há H1 e H2, retorna apenas os H1.
    """
    if not candidates:
        return []
    min_level = min(c["level"] for c in candidates)
    # Permite o nível imediatamente abaixo também, caso haja poucos H1
    top = [c for c in candidates if c["level"] <= min_level + 1]
    return top


# ---------------------------------------------------------------------------
# Etapa 3b: Chat — usado quando o parsing direto não é suficiente
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Você é um especialista em análise de estrutura de documentos PDF.

Receberá uma lista de possíveis títulos de capítulos extraídos por OCR, no formato:
  Página X: "texto"

Sua tarefa:
1. Identificar quais itens são REALMENTE capítulos ou seções principais (não subseções, rodapés ou ruídos).
2. Retornar APENAS um JSON válido, sem texto adicional, no formato:
   {"chapters": [{"title": "Título limpo", "start_page": N}, ...]}

Critérios para ser um capítulo:
- Títulos como "Capítulo 1", "1. Introdução", "Parte II", "Introduction", "Conclusão" etc.
- Títulos curtos e descritivos (normalmente < 80 caracteres).
- NÃO inclua: subseções (1.1, 1.2), rodapés, cabeçalhos de tabela, títulos de figuras.

Se nenhum candidato for um capítulo real, retorne {"chapters": []}.
"""


def _validate_via_chat(
    candidates: list[dict[str, Any]],
    api_key: str,
) -> list[dict[str, Any]]:
    """
    Envia os candidatos (compactos) ao modelo de chat para validação.
    Muito mais eficiente que enviar o texto completo.
    """
    lines = [
        f'Página {c["start_page"]}: "{c["title"]}"'
        for c in candidates
    ]
    user_content = "Candidatos a capítulos extraídos do PDF:\n\n" + "\n".join(lines)

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

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            f"{MISTRAL_BASE_URL}/chat/completions",
            headers=_auth_headers(api_key),
            json=payload,
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Erro na API de Chat (HTTP {resp.status_code}): {resp.text[:500]}"
        )

    raw = resp.json()["choices"][0]["message"]["content"]

    try:
        return json.loads(raw).get("chapters", [])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Resposta inválida do modelo: {raw[:200]}") from exc


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

async def identify_chapters(
    pages: list[dict[str, Any]],
    pdf_bytes: bytes | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Identifica capítulos do PDF com pipeline em três estágios.

    Returns:
        [{"chapter": str, "start_page": int, "end_page": int}, ...]
    """
    if pdf_bytes is None:
        raise ValueError("pdf_bytes é obrigatório.")

    key = _resolve_key(api_key)
    total_pages = pages[-1]["page_number"] if pages else 1

    # --- Etapa 1: OCR ---
    ocr_pages = _run_ocr(pdf_bytes, key)
    if not ocr_pages:
        raise ValueError("OCR não retornou páginas. PDF pode estar corrompido.")

    # --- Etapa 2: Parsing direto de headings ---
    candidates = _extract_heading_candidates(ocr_pages)
    top_candidates = _filter_top_level(candidates)

    # --- Etapa 3a: Direto (sem chat) se há headings claros suficientes ---
    MIN_DIRECT = 2  # mínimo de capítulos para aceitar sem validação via chat
    raw_chapters: list[dict[str, Any]]

    if len(top_candidates) >= MIN_DIRECT:
        raw_chapters = [
            {"title": c["title"], "start_page": c["start_page"]}
            for c in top_candidates
        ]
    else:
        # --- Etapa 3b: Valida via chat ---
        # Usa todos os candidatos (não só top-level) para dar mais contexto ao modelo
        all_candidates = candidates if candidates else _fallback_candidates(ocr_pages)
        raw_chapters = _validate_via_chat(all_candidates, key)

    if not raw_chapters:
        raise ValueError(
            "Nenhum capítulo identificado no documento.\n"
            "Dicas: verifique se o PDF tem títulos de capítulos visíveis, "
            "não está protegido por senha e não é um formulário ou apresentação."
        )

    # --- Calcula end_page e monta resultado final ---
    result: list[dict[str, Any]] = []
    for i, ch in enumerate(raw_chapters):
        start = max(1, int(ch.get("start_page", 1)))
        end = (
            max(start, int(raw_chapters[i + 1].get("start_page", start + 1)) - 1)
            if i + 1 < len(raw_chapters)
            else total_pages
        )
        result.append({
            "chapter": ch.get("title", f"Capítulo {i + 1}"),
            "start_page": start,
            "end_page": end,
        })

    return result


def _fallback_candidates(ocr_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Último recurso: envia as primeiras linhas não-vazias de cada página
    como candidatos. Útil para PDFs sem headings Markdown.
    """
    candidates = []
    for page in ocr_pages:
        page_num = page.get("index", 0) + 1
        markdown = page.get("markdown", "")
        first_lines = [l.strip() for l in markdown.splitlines() if l.strip()][:3]
        for line in first_lines:
            # Filtra linhas muito longas (provavelmente parágrafos)
            if 3 < len(line) < 100:
                candidates.append({"title": line, "start_page": page_num, "level": 5})
    return candidates[:50]  # limita para não sobrecarregar o chat
