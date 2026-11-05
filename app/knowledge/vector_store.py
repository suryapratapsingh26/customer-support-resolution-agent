from pathlib import Path
from typing import Any

from app.knowledge.chunking import Chunk


class VectorStoreError(RuntimeError):
    pass


class ChromaVectorStore:
    """Persistent Chroma adapter, with no Chroma-specific types escaping this module."""

    def __init__(self, persist_dir: str | Path, collection_name: str):
        self.persist_dir = str(persist_dir)
        self.collection_name = collection_name
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            try:
                import chromadb
                Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=self.persist_dir)
                self._collection = client.get_or_create_collection(
                    name=self.collection_name, metadata={"hnsw:space": "cosine"}
                )
            except Exception as exc:
                raise VectorStoreError(f"Could not open persistent vector store: {exc}") from exc
        return self._collection

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        result = self.collection.get(where={"document_id": document_id}, include=["metadatas"])
        if not result["ids"]:
            return None
        metadata = result["metadatas"][0]
        return {key: metadata.get(key) for key in (
            "document_id", "document_name", "document_type", "source_path",
            "category", "ingested_at", "content_hash",
        )}

    def upsert_document(self, chunks: list[Chunk], embeddings: list[list[float]], content_hash: str) -> None:
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise VectorStoreError("Chunk and embedding counts differ.")
        document_id = chunks[0].document_id
        try:
            current = self.get_document(document_id)
            if current and current.get("content_hash") == content_hash:
                return
            old_ids = []
            if current:
                old_ids = self.collection.get(
                    where={"document_id": document_id}, include=["metadatas"]
                )["ids"]
            metadatas = [dict(chunk.metadata, content_hash=content_hash) for chunk in chunks]
            self.collection.upsert(
                ids=[chunk.id for chunk in chunks], embeddings=embeddings,
                documents=[chunk.text for chunk in chunks], metadatas=metadatas,
            )
            stale_ids = set(old_ids) - {chunk.id for chunk in chunks}
            if stale_ids:
                self.collection.delete(ids=list(stale_ids))
        except Exception as exc:
            if isinstance(exc, VectorStoreError):
                raise
            raise VectorStoreError(f"Could not index document: {exc}") from exc

    def delete_document(self, document_id: str) -> bool:
        if not self.get_document(document_id):
            return False
        self.collection.delete(where={"document_id": document_id})
        return True

    def list_documents(self) -> list[dict[str, Any]]:
        result = self.collection.get(include=["metadatas"])
        documents: dict[str, dict[str, Any]] = {}
        for metadata in result["metadatas"] or []:
            documents.setdefault(metadata["document_id"], {
                key: metadata.get(key) for key in (
                    "document_id", "document_name", "document_type", "category", "ingested_at"
                )
            })
        return sorted(documents.values(), key=lambda item: (item["document_name"] or "").lower())

    def has_documents(self) -> bool:
        return self.collection.count() > 0

    def query(self, embedding: list[float], top_k: int, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = self.collection.query(
            query_embeddings=[embedding], n_results=top_k, where=where,
            include=["documents", "metadatas", "distances"],
        )
        if not result.get("ids") or not result["ids"][0]:
            return []
        return [
            {"id": chunk_id, "text": text, "metadata": metadata, "distance": distance}
            for chunk_id, text, metadata, distance in zip(
                result["ids"][0], result["documents"][0],
                result["metadatas"][0], result["distances"][0], strict=True,
            )
        ]
