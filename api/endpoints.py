import uuid
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from api.models import TaskStatus, TaskResponse
from services.pdf_service import extract_text_and_metadata
from services.nlp_service import identify_chapters
from services.file_service import split_and_package

router = APIRouter()

# In-memory task store (substituir por Redis em produção)
tasks: dict[str, TaskStatus] = {}


@router.post("/upload", response_model=TaskResponse, summary="Faz upload de um PDF para processamento")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Recebe um arquivo PDF, valida e inicia o processamento assíncrono.
    Retorna um Task ID para acompanhamento via polling.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="O arquivo enviado não é um PDF válido.")

    content = await file.read()

    task_id = str(uuid.uuid4())
    tasks[task_id] = TaskStatus(task_id=task_id, status="pending", progress=0)

    background_tasks.add_task(_process_pdf, task_id, content, file.filename)

    return TaskResponse(task_id=task_id, message="Processamento iniciado. Use o Task ID para verificar o status.")


@router.get("/status/{task_id}", response_model=TaskStatus, summary="Verifica o status de um processamento")
def get_task_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task não encontrada.")
    return task


@router.get("/download/{task_id}", summary="Faz download do ZIP gerado")
def download_result(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task não encontrada.")
    if task.status != "done":
        raise HTTPException(status_code=400, detail=f"Processamento ainda não concluído. Status: {task.status}")
    if not task.output_path:
        raise HTTPException(status_code=500, detail="Arquivo de saída não disponível.")

    return FileResponse(
        path=task.output_path,
        media_type="application/zip",
        filename=f"chapters_{task_id}.zip",
    )


async def _process_pdf(task_id: str, content: bytes, filename: str):
    """Função de background que executa o pipeline completo de processamento."""
    task = tasks[task_id]
    try:
        task.status = "extracting"
        task.progress = 10
        pages = extract_text_and_metadata(content)

        task.status = "analyzing"
        task.progress = 40
        chapters = await identify_chapters(pages)

        task.status = "splitting"
        task.progress = 75
        output_path = split_and_package(content, chapters, task_id)

        task.status = "done"
        task.progress = 100
        task.output_path = output_path

    except Exception as exc:
        task.status = "error"
        task.error = str(exc)
