"""
file_service.py
---------------
Gerencia arquivos temporários e empacotamento final em ZIP.
"""

from __future__ import annotations
import os
import zipfile
from pathlib import Path
from typing import Any

from services.pdf_service import split_pdf_by_chapters

# Diretório para armazenar arquivos temporários
TEMP_DIR = Path(__file__).parent.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


def split_and_package(
    pdf_bytes: bytes,
    chapters: list[dict[str, Any]],
    task_id: str,
) -> str:
    """
    Divide o PDF em capítulos e empacota em um arquivo ZIP.

    Args:
        pdf_bytes: bytes do PDF original
        chapters: lista de capítulos identificados pelo nlp_service
        task_id: identificador único da tarefa (usado para nomear o ZIP)

    Returns:
        Caminho absoluto do arquivo ZIP gerado.
    """
    chapter_files = split_pdf_by_chapters(pdf_bytes, chapters)

    zip_path = TEMP_DIR / f"{task_id}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, file_bytes in chapter_files:
            zf.writestr(filename, file_bytes)

    return str(zip_path)


def cleanup_task_files(task_id: str) -> None:
    """
    Remove o arquivo ZIP de uma task após o download do usuário.
    Chame esta função após servir o arquivo para o cliente.
    """
    zip_path = TEMP_DIR / f"{task_id}.zip"
    if zip_path.exists():
        zip_path.unlink()
