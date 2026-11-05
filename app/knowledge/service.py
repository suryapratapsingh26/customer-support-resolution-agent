import hashlib
from pathlib import Path
from typing import Any

from app.knowledge.chunking import TextChunker
from app.knowledge.context import assemble_context
from app.knowledge.embeddings import SentenceTransformerEmbedder
from app.knowledge.loaders import Document, DocumentLoadError, load_directory, load_document
from app.knowledge.vector_store import ChromaVectorStore


class KnowledgeBaseService:
    def __init__(self, directory: str | Path, store: ChromaVectorStore,
                 embedder: Any, chunker: TextChunker, context_max_chars: int = 12000,
                 default_top_k: int = 5):
        self.directory = Path(directory)
        self.store, self.embedder, self.chunker = store, embedder, chunker
        self.context_max_chars = context_max_chars
        self.default_top_k = default_top_k

    def _ingest(self, document: Document) -> dict[str, Any]:
        content_hash = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
        current = self.store.get_document(document.id)
        if current and current.get("content_hash") == content_hash:
            return {"document_id": document.id, "document_name": document.name, "status": "unchanged", "chunks": 0}
        chunks = self.chunker.split(document)
        vectors = self.embedder.embed([chunk.text for chunk in chunks]) if chunks else []
        self.store.upsert_document(chunks, vectors, content_hash)
        return {"document_id": document.id, "document_name": document.name, "status": "indexed", "chunks": len(chunks)}

    def ingest_directory(self) -> dict[str, Any]:
        documents, errors = load_directory(self.directory)
        results = []
        for document in documents:
            try:
                results.append(self._ingest(document))
            except Exception as exc:
                errors.append({"file": document.name, "error": str(exc)})
        return {"indexed": sum(r["status"] == "indexed" for r in results),
                "unchanged": sum(r["status"] == "unchanged" for r in results),
                "documents": results, "errors": errors}

    def ingest_file(self, filename: str) -> dict[str, Any]:
        path = (self.directory / filename).resolve()
        try:
            path.relative_to(self.directory.resolve())
        except ValueError as exc:
            raise DocumentLoadError("File must be inside the configured knowledge directory.") from exc
        if not path.is_file():
            raise DocumentLoadError("Knowledge document was not found.")
        return self._ingest(load_document(path, self.directory))

    def list_documents(self) -> list[dict[str, Any]]:
        return self.store.list_documents()

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.store.get_document(document_id)

    def delete_document(self, document_id: str) -> bool:
        return self.store.delete_document(document_id)

    def search(self, query: str, top_k: int | None = None, category: str | None = None,
               document_type: str | None = None) -> dict[str, Any]:
        if not query.strip():
            return {"query": query, "results": [], "context": ""}
        if not self.store.has_documents():
            return {"query": query, "results": [], "context": ""}
        filters = [{key: value} for key, value in (
            ("category", category), ("document_type", document_type)
        ) if value]
        where = filters[0] if len(filters) == 1 else {"$and": filters} if filters else None
        vector = self.embedder.embed([query.strip()])[0]
        results = self.store.query(vector, top_k=top_k or self.default_top_k, where=where)
        unique, seen = [], set()
        for result in results:
            key = (result["metadata"].get("document_id"), result["text"])
            if key not in seen:
                unique.append(result)
                seen.add(key)
        return {"query": query, "results": unique,
                "context": assemble_context(unique, self.context_max_chars)}


def build_knowledge_service(settings) -> KnowledgeBaseService:
    return KnowledgeBaseService(
        directory=settings.knowledge_base_dir,
        store=ChromaVectorStore(settings.chroma_persist_dir, settings.chroma_collection_name),
        embedder=SentenceTransformerEmbedder(settings.embedding_model_name, settings.embedding_device),
        chunker=TextChunker(settings.knowledge_chunk_size, settings.knowledge_chunk_overlap),
        context_max_chars=settings.knowledge_context_max_chars,
        default_top_k=settings.knowledge_top_k,
    )
