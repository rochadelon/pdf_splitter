"""
nlp_service.py
--------------
Motor principal: Mistral OCR (`mistral-ocr-latest`).

Pipeline:
  1. Faz upload do PDF como base64 para a API do Mistral.
  2. Chama `client.ocr.process` com `annotation_schema` para extrair
     os capítulos em JSON estruturado em uma única requisição.
  3. Calcula `end_page` de cada capítulo com base no `start_page` do próximo.

Vantagem sobre a abordagem anterior:
  - Funciona nativamente com PDFs escaneados (sem texto selecionável).
  - Não precisa de filtro heurístico — o modelo lê o layout visual diretamente.
  - Uma única chamada de API substitui o filtro + loop de validação LLM.
"""

from __future__ import annotations

import base64
import os
from typing import Any

from mistralai import Mistral
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

_client: Mistral | None = None


def _get_client(api_key: str | None = None) -> Mistral:
    """Retorna um cliente Mistral.

    Se `api_key` for fornecida (vinda do frontend), cria uma instância dedicada
    para a requisição. Caso contrário, reutiliza o singleton configurado via env.
    """
    global _client
    if api_key:
        return Mistral(api_key=api_key)
    if _client is None:
        if not MISTRAL_API_KEY:
            raise EnvironmentError(
                "Nenhuma MISTRAL_API_KEY configurada. Insira sua chave na interface "
                "ou defina a variável de ambiente MISTRAL_API_KEY."
            )
        _client = Mistral(api_key=MISTRAL_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Schema de saída estruturada (Pydantic → annotation_schema)
# ---------------------------------------------------------------------------


class ChapterAnnotation(BaseModel):
    """Representa um capítulo identificado pelo Mistral OCR."""

    title: str = Field(
        ...,
        description=(
            "Título completo do capítulo ou seção principal, "
            "exatamente como aparece no documento."
        ),
    )
    start_page: int = Field(
        ...,
        description="Número da primeira página do capítulo (1-indexed).",
    )


class DocumentChapters(BaseModel):
    """Schema raiz retornado pelo annotation_schema do Mistral OCR."""

    chapters: list[ChapterAnnotation] = Field(
        ...,
        description=(
            "Lista de todos os capítulos e seções principais identificados "
            "no documento, em ordem de aparecimento."
        ),
    )


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------


async def identify_chapters(
    pages: list[dict[str, Any]],
    pdf_bytes: bytes | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Identifica os capítulos do PDF usando o Mistral OCR.

    Args:
        pages: saída do `pdf_service.extract_text_and_metadata` (usado para
               obter o total de páginas e como fallback heurístico).
        pdf_bytes: bytes brutos do PDF original — necessário para enviar ao
                   Mistral OCR via base64.

    Returns:
        Lista de dicts: [{"chapter": str, "start_page": int, "end_page": int}, ...]
    """
    if pdf_bytes is None:
        raise ValueError("pdf_bytes é obrigatório para o Mistral OCR.")

    client = _get_client(api_key)

    # Codifica o PDF em base64 no formato data URI
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    document_url = f"data:application/pdf;base64,{b64}"

    # Chama o Mistral OCR com schema estruturado
    ocr_response = client.ocr.process(
        model=MISTRAL_OCR_MODEL,
        document={
            "type": "document_url",
            "document_url": document_url,
        },
        annotation_schema=DocumentChapters,
    )

    # Extrai as anotações da primeira página (o schema é global ao documento)
    annotations = None
    for page in ocr_response.pages:
        if page.annotations:
            annotations = page.annotations
            break

    if not annotations or not annotations.chapters:
        raise ValueError(
            "O Mistral OCR não identificou capítulos no documento. "
            "Verifique se o PDF possui estrutura de capítulos reconhecível."
        )

    total_pages = pages[-1]["page_number"] if pages else 1

    # Monta a lista final com end_page calculado
    chapters: list[dict[str, Any]] = []
    for i, ch in enumerate(annotations.chapters):
        if i + 1 < len(annotations.chapters):
            end_page = annotations.chapters[i + 1].start_page - 1
        else:
            end_page = total_pages

        chapters.append(
            {
                "chapter": ch.title,
                "start_page": ch.start_page,
                "end_page": end_page,
            }
        )

    return chapters
