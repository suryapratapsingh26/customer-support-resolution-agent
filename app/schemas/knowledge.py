from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    filename: str | None = Field(default=None, min_length=1, max_length=255)


class IngestResult(BaseModel):
    indexed: int = 0
    unchanged: int = 0
    documents: list[dict] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    category: str | None = Field(default=None, max_length=100)
    document_type: str | None = Field(default=None, pattern="^(pdf|md|txt)$")


class SearchResult(BaseModel):
    id: str
    text: str
    metadata: dict
    distance: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    context: str
