"""
pdf_service.py
--------------
Responsável por toda a interação com PyMuPDF (fitz):
  - Extração de texto e metadados estruturais por página
  - Split físico do PDF em novos documentos por capítulo
"""

from __future__ import annotations
import io
from typing import Any
import fitz  # PyMuPDF


def extract_text_and_metadata(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """
    Abre o PDF a partir de bytes e extrai texto + metadados de cada página.

    Retorna uma lista de dicionários com:
      - page_number (int): número da página (1-indexed)
      - text (str): texto bruto da página
      - avg_font_size (float): tamanho médio de fonte detectado
      - has_large_font (bool): True se alguma linha tem fonte ≥ 1.5× a média do documento
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[dict[str, Any]] = []

    # Calcula tamanho médio de fonte no documento inteiro para referência
    all_sizes: list[float] = []
    for page in doc:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] == 0:  # bloco de texto
                for line in block["lines"]:
                    for span in line["spans"]:
                        all_sizes.append(span["size"])

    doc_avg_font_size = sum(all_sizes) / len(all_sizes) if all_sizes else 12.0

    for page in doc:
        page_num = page.number + 1  # 1-indexed
        raw_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        raw_text = page.get_text("text")

        page_sizes: list[float] = []
        has_large_font = False

        for block in raw_dict["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    for span in line["spans"]:
                        page_sizes.append(span["size"])
                        if span["size"] >= doc_avg_font_size * 1.5:
                            has_large_font = True

        avg_font_size = sum(page_sizes) / len(page_sizes) if page_sizes else doc_avg_font_size

        pages.append(
            {
                "page_number": page_num,
                "text": raw_text,
                "avg_font_size": round(avg_font_size, 2),
                "has_large_font": has_large_font,
                "doc_avg_font_size": round(doc_avg_font_size, 2),
            }
        )

    doc.close()
    return pages


def split_pdf_by_chapters(
    pdf_bytes: bytes,
    chapters: list[dict[str, Any]],
) -> list[tuple[str, bytes]]:
    """
    Divide o PDF original em múltiplos PDFs com base nos intervalos de páginas.

    Args:
        pdf_bytes: conteúdo original do PDF
        chapters: lista de dicts com keys 'chapter', 'start_page', 'end_page'

    Returns:
        Lista de tuplas (filename, pdf_bytes) para cada capítulo.
    """
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    results: list[tuple[str, bytes]] = []

    for idx, chapter in enumerate(chapters, start=1):
        title: str = chapter["chapter"]
        start: int = chapter["start_page"] - 1  # fitz usa 0-indexed
        end: int = chapter["end_page"] - 1

        new_doc = fitz.open()
        new_doc.insert_pdf(src, from_page=start, to_page=end)

        # Sanitiza o nome do arquivo
        safe_title = _sanitize_filename(title)
        filename = f"{idx:02d}_{safe_title}.pdf"

        buffer = io.BytesIO()
        new_doc.save(buffer)
        new_doc.close()

        results.append((filename, buffer.getvalue()))

    src.close()
    return results


def _sanitize_filename(name: str) -> str:
    """Remove caracteres inválidos para nomes de arquivo."""
    invalid_chars = r'\/:*?"<>|'
    for ch in invalid_chars:
        name = name.replace(ch, "")
    return name.strip().replace(" ", "_")
