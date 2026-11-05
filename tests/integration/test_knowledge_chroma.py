import os
import subprocess
import sys

import pytest

from app.knowledge.chunking import TextChunker
from app.knowledge.loaders import Document
from app.knowledge.vector_store import ChromaVectorStore
from app.knowledge.service import KnowledgeBaseService
from app.knowledge.embeddings import SentenceTransformerEmbedder


def test_chroma_persists_and_filters_documents(tmp_path):
    pytest.importorskip("chromadb")
    path = tmp_path / "vectors"
    store = ChromaVectorStore(path, "test_support")
    document = Document("doc-1", "refund.md", "md", "refunds/refund.md", "refunds", "Refunds are returned in five days.")
    chunks = TextChunker(100, 10).split(document)
    store.upsert_document(chunks, [[1.0, 0.0]], "hash-1")
    reopened = ChromaVectorStore(path, "test_support")
    assert reopened.get_document("doc-1")["content_hash"] == "hash-1"
    code = (
        "import sys; from app.knowledge.vector_store import ChromaVectorStore; "
        "store=ChromaVectorStore(sys.argv[1], 'test_support'); "
        "assert store.get_document('doc-1')['content_hash'] == 'hash-1'; "
        "print(len(store.list_documents()))"
    )
    restarted = subprocess.run(
        [sys.executable, "-c", code, str(path)], check=True,
        capture_output=True, text=True,
    )
    assert restarted.stdout.strip() == "1"
    result = reopened.query([1.0, 0.0], 3, {"category": "refunds"})
    assert result[0]["text"] == chunks[0].text
    assert reopened.delete_document("doc-1")
    assert reopened.list_documents() == []


@pytest.mark.skipif(
    os.getenv("RUN_REAL_EMBEDDING_TESTS") != "1",
    reason="Set RUN_REAL_EMBEDDING_TESTS=1 to use the configured local model.",
)
def test_real_embedding_semantic_retrieval(tmp_path):
    pytest.importorskip("sentence_transformers")
    root = tmp_path / "knowledge"
    (root / "refunds").mkdir(parents=True)
    (root / "shipping").mkdir()
    (root / "refunds" / "refund.md").write_text(
        "Approved refunds go back to the original payment method. Banks usually post them within 5 to 10 business days.",
        encoding="utf-8",
    )
    (root / "shipping" / "shipping.md").write_text(
        "Standard domestic delivery is usually 3 to 7 business days after dispatch.",
        encoding="utf-8",
    )
    service = KnowledgeBaseService(
        root,
        ChromaVectorStore(tmp_path / "vectors", "real_embedding_test"),
        SentenceTransformerEmbedder("sentence-transformers/all-MiniLM-L6-v2"),
        TextChunker(500, 50),
    )
    result = service.ingest_directory()
    assert result["indexed"] == 2
    search = service.search("How long until an approved refund reaches my bank?", category="refunds")
    assert search["results"]
    assert "5 to 10 business days" in search["results"][0]["text"]
