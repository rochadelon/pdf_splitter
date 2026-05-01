from pydantic import BaseModel
from typing import Optional


class ChapterInfo(BaseModel):
    """Representa um capítulo identificado no PDF."""
    chapter: str
    start_page: int
    end_page: int


class TaskResponse(BaseModel):
    """Resposta imediata ao fazer upload de um PDF."""
    task_id: str
    message: str


class TaskStatus(BaseModel):
    """Estado atual de um processamento assíncrono."""
    task_id: str
    status: str  # pending | extracting | analyzing | splitting | done | error
    progress: int = 0  # 0-100
    output_path: Optional[str] = None
    error: Optional[str] = None
