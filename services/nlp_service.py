"""
nlp_service.py
--------------
Motor semântico: identifica capítulos usando um funil em duas etapas:
  1. Filtro heurístico (RegEx + análise de fonte) para pré-selecionar candidatos.
  2. Validação via LLM (OpenAI ou Anthropic) para confirmar e extrair títulos.
"""

from __future__ import annotations
import re
import json
import os
from typing import Any

import httpx
from openai import AsyncOpenAI

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Padrões heurísticos de capítulo
# ---------------------------------------------------------------------------

CHAPTER_PATTERNS = [
    r"(?i)^\s*(cap[ií]tulo|chapter|parte|part|se[çc][aã]o|section)\s*[\d\w]+",
    r"(?i)^\s*[\d]+[\.\)]\s+[A-ZÁÉÍÓÚÀÃÕ][^\n]{3,60}$",
    r"(?i)^\s*(introdu[çc][aã]o|introduction|conclus[aã]o|conclusion|refer[eê]ncias|references)\s*$",
]

_compiled_patterns = [re.compile(p, re.MULTILINE) for p in CHAPTER_PATTERNS]


def _heuristic_filter(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Retorna apenas as páginas que são candidatas a início de capítulo,
    com base em RegEx e tamanho de fonte.
    """
    candidates: list[dict[str, Any]] = []
    for page in pages:
        text = page["text"]
        is_regex_match = any(p.search(text) for p in _compiled_patterns)
        is_large_font = page.get("has_large_font", False)

        if is_regex_match or is_large_font:
            candidates.append(page)

    return candidates


# ---------------------------------------------------------------------------
# Validação via LLM
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Você é um assistente especializado em análise de estrutura de documentos.
Dado o texto de uma página de PDF, determine se ela representa o início de um novo capítulo ou seção principal.
Responda SEMPRE com um JSON válido no formato:
{"is_chapter_start": true/false, "title": "Título exato do capítulo ou null"}
Não inclua nenhum texto fora do JSON."""


async def _validate_with_llm(page: dict[str, Any]) -> dict[str, Any] | None:
    """
    Envia a página ao LLM para validação. Retorna o capítulo identificado ou None.
    """
    text_snippet = page["text"][:800]  # limita o contexto enviado ao LLM
    user_message = (
        f"Página {page['page_number']}.\n"
        f"Tem fonte grande: {'Sim' if page['has_large_font'] else 'Não'}.\n\n"
        f"Conteúdo:\n{text_snippet}"
    )

    client = _get_client()
    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        max_tokens=150,
    )

    raw = response.choices[0].message.content or ""
    try:
        result = json.loads(raw)
        if result.get("is_chapter_start") and result.get("title"):
            return {"chapter": result["title"], "start_page": page["page_number"]}
    except json.JSONDecodeError:
        pass

    return None


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------


async def identify_chapters(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Pipeline completo: filtra candidatos e valida via LLM.

    Retorna lista de dicts:
        [{"chapter": "1 - Introdução", "start_page": 5, "end_page": 18}, ...]
    """
    candidates = _heuristic_filter(pages)

    if not candidates:
        raise ValueError(
            "Nenhum candidato a capítulo encontrado. "
            "O PDF pode ser escaneado ou ter estrutura não convencional."
        )

    # Valida candidatos com o LLM
    validated: list[dict[str, Any]] = []
    for page in candidates:
        result = await _validate_with_llm(page)
        if result:
            validated.append(result)

    if not validated:
        raise ValueError("O LLM não conseguiu identificar capítulos no documento.")

    # Calcula end_page de cada capítulo com base no start_page do próximo
    total_pages = pages[-1]["page_number"]
    for i, chapter in enumerate(validated):
        if i + 1 < len(validated):
            chapter["end_page"] = validated[i + 1]["start_page"] - 1
        else:
            chapter["end_page"] = total_pages

    return validated
