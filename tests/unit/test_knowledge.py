import hashlib
import sys
from types import SimpleNamespace

import pytest

from app.knowledge.chunking import TextChunker
from app.knowledge.context import assemble_context
from app.knowledge.embeddings import EmbeddingError, SentenceTransformerEmbedder
from app.knowledge.loaders import Document, DocumentLoadError, load_directory, load_document
from app.knowledge.service import KnowledgeBaseService


class FakeEmbedder:
    def embed(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


class FakeStore:
    def __init__(self):
        self.docs = {}
        self.chunks = {}

    def get_document(self, doc_id):
        return self.docs.get(doc_id)

    def upsert_document(self, chunks, vectors, content_hash):
        first = chunks[0]
        self.docs[first.document_id] = dict(first.metadata, content_hash=content_hash)
        self.chunks[first.document_id] = [
            {"id": c.id, "text": c.text, "metadata": c.metadata, "distance": 0.1} for c in chunks
        ]

    def list_documents(self):
        return list(self.docs.values())

    def delete_document(self, doc_id):
        if doc_id not in self.docs:
            return False
        del self.docs[doc_id]
        del self.chunks[doc_id]
        return True

    def query(self, embedding, top_k, where=None):
        items = [chunk for chunks in self.chunks.values() for chunk in chunks]
        if where:
            filters = where.get("$and", [where])
            items = [c for c in items if all(c["metadata"].get(k) == v for item in filters for k, v in item.items())]
        return items[:top_k]

    def has_documents(self):
        return bool(self.docs)


def test_load_markdown_text_and_normalize(tmp_path):
    root = tmp_path / "kb"
    category = root / "refunds"
    category.mkdir(parents=True)
    path = category / "policy.md"
    path.write_text("# Refunds\r\n\r\n  Full\trefund.\x00", encoding="utf-8")
    doc = load_document(path, root)
    assert doc.document_type == "md"
    assert doc.category == "refunds"
    assert doc.source_path == "refunds/policy.md"
    assert doc.text == "# Refunds\n\nFull refund."


def test_empty_unsupported_and_directory_errors(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text(" \n")
    with pytest.raises(DocumentLoadError):
        load_document(empty)
    with pytest.raises(DocumentLoadError):
        load_document(tmp_path / "archive.docx")
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
    _, errors = load_directory(tmp_path)
    assert len(errors) == 2


def test_pdf_extraction_when_dependency_installed(tmp_path):
    pytest.importorskip("pypdf")
    content = b"BT /F1 12 Tf 72 720 Td (PDF refund policy extraction works.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
    path = tmp_path / "policy.pdf"
    path.write_bytes(pdf)
    assert "PDF refund policy extraction works." in load_document(path).text


def test_empty_pdf_is_rejected(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    path = tmp_path / "empty.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(DocumentLoadError, match="no extractable text"):
        load_document(path)


def test_pdf_text_extraction(tmp_path, monkeypatch):
    class Reader:
        def __init__(self, path, strict):
            self.pages = [SimpleNamespace(extract_text=lambda: "Refund policy"),
                          SimpleNamespace(extract_text=lambda: "Five business days.")]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=Reader))
    path = tmp_path / "refund.pdf"
    path.write_bytes(b"synthetic pdf placeholder")
    doc = load_document(path)
    assert doc.document_type == "pdf"
    assert doc.text == "Refund policy\n\nFive business days."


def test_chunking_preserves_metadata_and_stable_ids():
    document = Document("doc1", "policy.md", "md", "refunds/policy.md", "refunds", "Rule one. " * 40)
    chunker = TextChunker(80, 10)
    first, second = chunker.split(document), chunker.split(document)
    assert len(first) > 1
    assert [c.id for c in first] == [c.id for c in second]
    assert all(c.metadata["category"] == "refunds" for c in first)
    assert all(c.text for c in first)
    with pytest.raises(ValueError):
        TextChunker(10, 10)


def test_ingestion_idempotency_update_delete_and_search(tmp_path):
    root = tmp_path / "kb"
    category = root / "refunds"
    category.mkdir(parents=True)
    path = category / "policy.txt"
    path.write_text("Refunds take five business days.")
    store = FakeStore()
    service = KnowledgeBaseService(root, store, FakeEmbedder(), TextChunker(100, 10))
    first = service.ingest_directory()
    second = service.ingest_directory()
    assert first["indexed"] == 1 and second["unchanged"] == 1
    assert len(store.chunks) == 1
    search = service.search("refund timing", category="refunds")
    assert "policy.txt" in search["context"]
    assert service.search("refund timing", category="refunds", document_type="txt")["results"]
    assert service.search("", 5)["results"] == []
    path.write_text("Refunds take ten business days.")
    service.ingest_directory()
    expected_hash = hashlib.sha256(path.read_text().encode()).hexdigest()
    assert next(iter(store.docs.values()))["content_hash"] == expected_hash
    doc_id = next(iter(store.docs))
    assert service.delete_document(doc_id)
    assert service.list_documents() == []


def test_empty_store_does_not_load_embedding_model():
    class NoEmbedder:
        def embed(self, texts):
            raise AssertionError("empty stores should not embed queries")

    service = KnowledgeBaseService(".", FakeStore(), NoEmbedder(), TextChunker())
    assert service.search("refund") == {"query": "refund", "results": [], "context": ""}


def test_context_deduplicates_and_respects_limit():
    chunks = [
        {"id": "1", "text": "Policy details.", "metadata": {"document_name": "Refunds", "category": "refunds"}},
        {"id": "1", "text": "Policy details.", "metadata": {"document_name": "Refunds", "category": "refunds"}},
    ]
    context = assemble_context(chunks, max_chars=100)
    assert context.count("Policy details") == 1
    assert "Refunds" in context
    assert len(assemble_context(chunks, max_chars=10)) <= 10


def test_embedder_rejects_invalid_input():
    embedder = SentenceTransformerEmbedder("missing")
    with pytest.raises(EmbeddingError):
        embedder.embed([""])


def test_embedder_rejects_wrong_output_dimension(monkeypatch):
    class WrongDimensionModel:
        def get_embedding_dimension(self):
            return 3

        def encode(self, texts, **kwargs):
            return [[0.1, 0.2] for _ in texts]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=lambda *args, **kwargs: WrongDimensionModel()),
    )
    embedder = SentenceTransformerEmbedder("test-model")
    with pytest.raises(EmbeddingError, match="invalid embedding"):
        embedder.embed(["test query"])
