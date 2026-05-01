"""
nlp_service.py
--------------
Motor semântico via REST API do Mistral — sem SDK, apenas httpx.

Pipeline:
  1. Chama POST /v1/ocr para extrair o texto de cada página em Markdown.
  2. Chama POST /v1/chat/completions (JSON mode) para identificar capítulos
     e páginas de início a partir do texto extraído.

Vantagens desta abordagem:
  - Independente de versão do SDK mistralai.
  - Funciona com qualquer Python (3.9+).
  - Mais fácil de depurar (respostas HTTP puras).
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
MISTRAL_CHAT_MODEL = os.getenv("MISTRAL_CHAT_MODEL", "mistral-small-latest")
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

_TIMEOUT = httpx.Timeout(120.0)  # PDFs grandes podem demorar


def _resolve_key(api_key: str | None) -> str:
    """Retorna a chave de API: da chamada ou da variável de ambiente."""
    key = api_key or MISTRAL_API_KEY
    if not key:
        raise EnvironmentError(
            "Nenhuma MISTRAL_API_KEY configurada. "
            "Insira sua chave na barra lateral ou defina a variável de ambiente MISTRAL_API_KEY."
        )
    return key


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Etapa 1: OCR — extrai texto de cada página em Markdown
# ---------------------------------------------------------------------------

def _run_ocr(pdf_bytes: bytes, api_key: str) -> list[dict[str, Any]]:
    """
    Chama a API de OCR do Mistral e retorna a lista de páginas com seus
    textos em Markdown.
    """
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    document_url = f"data:application/pdf;base64,{b64}"

    payload = {
        "model": MISTRAL_OCR_MODEL,
        "document": {
            "type": "document_url",
            "document_url": document_url,
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
            f"Erro na API de OCR do Mistral (HTTP {resp.status_code}): {resp.text}"
        )

    data = resp.json()
    return data.get("pages", [])


# ---------------------------------------------------------------------------
# Etapa 2: Chat — identifica capítulos em JSON a partir do texto OCR
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Você é um especialista em análise de estrutura de documentos.
Analise o texto abaixo, extraído de um PDF via OCR, e identifique todos os
capítulos e seções principais do documento.

Responda APENAS com um objeto JSON válido, sem texto adicional, no formato:
{
  "chapters": [
    {"title": "Título do capítulo", "start_page": 1},
    ...
  ]
}

Regras:
- "title" deve ser o título exato como aparece no documento.
- "start_page" é o número da página onde o capítulo começa (1-indexed).
- Inclua apenas capítulos/seções de nível superior (não subseções).
- Se não houver capítulos identificáveis, retorne {"chapters": []}.
"""


def _extract_chapters_via_chat(
    ocr_pages: list[dict[str, Any]],
    api_key: str,
) -> list[dict[str, Any]]:
    """
    Envia o texto OCR ao modelo de chat do Mistral e pede a extração
    dos capítulos em JSON.
    """
    # Monta o contexto: número da página + texto Markdown de cada página
    context_parts: list[str] = []
    for page in ocr_pages:
        page_num = page.get("index", 0) + 1  # a API retorna index 0-based
        text = page.get("markdown", "").strip()
        if text:
            context_parts.append(f"--- Página {page_num} ---\n{text}")

    # Limita o contexto para não estourar o limite de tokens (~30k chars)
    full_context = "\n\n".join(context_parts)
    if len(full_context) > 30_000:
        full_context = full_context[:30_000] + "\n\n[... restante omitido ...]"

    payload = {
        "model": MISTRAL_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": full_context},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            f"{MISTRAL_BASE_URL}/chat/completions",
            headers=_auth_headers(api_key),
            json=payload,
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Erro na API de Chat do Mistral (HTTP {resp.status_code}): {resp.text}"
        )

    raw_content = resp.json()["choices"][0]["message"]["content"]

    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Resposta do modelo não é JSON válido: {raw_content}") from exc

    return result.get("chapters", [])


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------


async def identify_chapters(
    pages: list[dict[str, Any]],
    pdf_bytes: bytes | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Pipeline completo: OCR → extração de capítulos via chat.

    Args:
        pages: saída de pdf_service.extract_text_and_metadata (usado para
               calcular o total de páginas).
        pdf_bytes: bytes do PDF original.
        api_key: chave Mistral fornecida pelo usuário (sobrescreve env var).

    Returns:
        [{"chapter": str, "start_page": int, "end_page": int}, ...]
    """
    if pdf_bytes is None:
        raise ValueError("pdf_bytes é obrigatório para chamar o Mistral OCR.")

    key = _resolve_key(api_key)

    # Etapa 1: OCR
    ocr_pages = _run_ocr(pdf_bytes, key)

    if not ocr_pages:
        raise ValueError(
            "O Mistral OCR não retornou páginas. "
            "Verifique se o PDF não está corrompido ou protegido por senha."
        )

    # Etapa 2: identificação de capítulos
    raw_chapters = _extract_chapters_via_chat(ocr_pages, key)

    if not raw_chapters:
        raise ValueError(
            "Nenhum capítulo identificado. "
            "Verifique se o PDF possui estrutura de capítulos reconhecível."
        )

    total_pages = pages[-1]["page_number"] if pages else len(ocr_pages)

    # Calcula end_page e normaliza o campo "chapter"
    result: list[dict[str, Any]] = []
    for i, ch in enumerate(raw_chapters):
        start = int(ch.get("start_page", 1))
        if i + 1 < len(raw_chapters):
            end = int(raw_chapters[i + 1].get("start_page", start + 1)) - 1
        else:
            end = total_pages

        result.append(
            {
                "chapter": ch.get("title", f"Capítulo {i + 1}"),
                "start_page": start,
                "end_page": end,
            }
        )

    return result
