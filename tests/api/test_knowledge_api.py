from app.api.v1.routes import knowledge


class StubKnowledge:
    def ingest_directory(self):
        return {"indexed": 1, "unchanged": 0, "documents": [], "errors": []}

    def ingest_file(self, filename):
        return {"document_id": "abc", "document_name": filename, "status": "indexed", "chunks": 2}

    def list_documents(self):
        return [{"document_id": "abc", "document_name": "policy.md", "category": "refunds"}]

    def get_document(self, document_id):
        return {"document_id": document_id, "document_name": "policy.md"} if document_id == "abc" else None

    def delete_document(self, document_id):
        return document_id == "abc"

    def search(self, query, top_k=None, category=None, document_type=None):
        return {"query": query, "results": [{"id": "c1", "text": "Refunds take 5 days.", "metadata": {"category": "refunds"}, "distance": 0.1}], "context": "[Source: policy.md]\nRefunds take 5 days."}


def test_knowledge_api_endpoints(client, monkeypatch):
    monkeypatch.setattr(knowledge, "_service", lambda: StubKnowledge())
    assert client.post("/api/v1/knowledge/ingest").status_code == 200
    assert client.post("/api/v1/knowledge/ingest", json={"filename": "refunds/policy.md"}).json()["indexed"] == 1
    assert client.get("/api/v1/knowledge/documents").json()[0]["category"] == "refunds"
    assert client.get("/api/v1/knowledge/documents/abc").status_code == 200
    assert client.get("/api/v1/knowledge/documents/missing").status_code == 404
    assert client.delete("/api/v1/knowledge/documents/abc").status_code == 204
    assert client.post("/api/v1/knowledge/search", json={"query": "refund timing"}).json()["results"][0]["distance"] == 0.1
    assert client.post("/api/v1/knowledge/search", json={"query": "  "}).status_code == 422


def test_ingest_rejects_traversal(client, monkeypatch):
    from app.knowledge.loaders import DocumentLoadError

    class TraversalStub(StubKnowledge):
        def ingest_file(self, filename):
            raise DocumentLoadError("File must be inside the configured knowledge directory.")

    monkeypatch.setattr(knowledge, "_service", lambda: TraversalStub())
    response = client.post("/api/v1/knowledge/ingest", json={"filename": "../secret.txt"})
    assert response.status_code == 400
