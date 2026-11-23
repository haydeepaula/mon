import uuid

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.schemas.documents import (
    DocumentClassify,
    DocumentOut,
    DocumentStats,
    DocumentVocabulary,
    UploadItemOut,
)
from app.api.schemas.jobs import JobOut
from app.container import get_file_storage, get_loader_factory, get_vector_store
from app.core.exceptions import ConflictError
from app.domain.knowledge_base import TIPOS_DOCUMENTO, Colecao
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documentos"])


def _service(db) -> DocumentService:
    return DocumentService(db, get_file_storage(), get_vector_store(), get_loader_factory())


@router.get("", response_model=list[DocumentOut])
def list_documents(
    _: AdminUser, db: DbSession, q: str | None = None, status_filter: str | None = None, colecao: str | None = None
):
    return _service(db).search(q, status_filter, colecao)


@router.get("/vocabulary", response_model=DocumentVocabulary)
def document_vocabulary(_: AdminUser):
    """Coleções lógicas e tipos de documento aceitos em cada uma."""
    return DocumentVocabulary(
        colecoes=[c.value for c in Colecao],
        tipos_documento={c.value: list(tipos) for c, tipos in TIPOS_DOCUMENTO.items()},
    )


@router.get("/stats", response_model=DocumentStats)
def document_stats(_: AdminUser, db: DbSession):
    stats = DocumentRepository(db).stats()
    try:
        vectors = get_vector_store().count()
    except Exception:
        vectors = None
    return DocumentStats(**stats, vectors=vectors, supported_extensions=get_loader_factory().supported_extensions)


@router.get("/names", response_model=list[str])
def document_names(_: AdminUser, db: DbSession):
    return DocumentRepository(db).filenames()


@router.post("/upload", response_model=list[UploadItemOut])
def upload_documents(
    user: AdminUser,
    db: DbSession,
    files: list[UploadFile] = File(...),
    colecao: str | None = Form(None),
    tipo_documento: str | None = Form(None),
    curso: str | None = Form(None),
):
    service = _service(db)
    items: list[UploadItemOut] = []
    for upload in files:
        result = service.upload(upload.filename or "arquivo", upload.file, user.id, colecao, tipo_documento, curso)
        db.commit()
        items.append(
            UploadItemOut(
                filename=result.filename,
                status=result.status,
                message=result.message,
                document=DocumentOut.model_validate(result.document) if result.document else None,
                job_id=result.job.id if result.job else None,
            )
        )
    return items


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, _: AdminUser, db: DbSession):
    return _service(db).get(document_id)


@router.patch("/{document_id}", response_model=DocumentOut)
def classify_document(document_id: uuid.UUID, payload: DocumentClassify, _: AdminUser, db: DbSession):
    """Reclassifica o documento (coleção, tipo, curso) sem reindexar."""
    document = _service(db).classify(document_id, payload.colecao, payload.tipo_documento, payload.curso)
    db.commit()
    return document


@router.get("/{document_id}/download")
def download_document(document_id: uuid.UUID, _: CurrentUser, db: DbSession):
    path, document = _service(db).file_path(document_id)
    return FileResponse(path, filename=document.filename, media_type=document.mime_type or "application/octet-stream")


@router.post("/{document_id}/reindex", response_model=JobOut)
def reindex_document(document_id: uuid.UUID, user: AdminUser, db: DbSession):
    job = _service(db).reindex(document_id, user.id)
    if job is None:
        raise ConflictError("Este documento já está na fila de indexação.")
    return job


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, _: AdminUser, db: DbSession):
    _service(db).delete(document_id)
