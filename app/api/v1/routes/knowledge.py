from functools import lru_cache

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.knowledge.embeddings import EmbeddingError
from app.knowledge.loaders import DocumentLoadError
from app.knowledge.service import build_knowledge_service
from app.knowledge.vector_store import VectorStoreError
from app.schemas.knowledge import IngestRequest, IngestResult, SearchRequest, SearchResponse

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@lru_cache(maxsize=1)
def _service():
    return build_knowledge_service(settings)


@router.post("/ingest", response_model=IngestResult)
def ingest(request: IngestRequest | None = None):
    try:
        if request and request.filename:
            result = _service().ingest_file(request.filename)
            return {"indexed": int(result["status"] == "indexed"),
                    "unchanged": int(result["status"] == "unchanged"), "documents": [result], "errors": []}
        return _service().ingest_directory()
    except DocumentLoadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (EmbeddingError, VectorStoreError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/documents")
def list_documents():
    try:
        return _service().list_documents()
    except VectorStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    try:
        document = _service().get_document(document_id)
    except VectorStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str):
    try:
        deleted = _service().delete_document(document_id)
    except VectorStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest):
    if not request.query.strip():
        raise HTTPException(status_code=422, detail="Query must not be blank.")
    try:
        return _service().search(request.query, request.top_k, request.category, request.document_type)
    except (EmbeddingError, VectorStoreError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
