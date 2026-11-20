from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSource(BaseModel):
    id: str
    document_id: str | None = None
    document_name: str | None = None
    category: str | None = None
    text: str
    distance: float | None = None


class ResolutionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    issue_category: str
    issue_summary: str
    customer_context_summary: str
    retrieved_knowledge_sources: list[KnowledgeSource]
    proposed_resolution: str
    explanation: str
    confidence_score: float = Field(ge=0, le=1)
    missing_information: list[str] = Field(default_factory=list)
    human_review_recommended: bool = True
    action_required: bool = False
    required_action: str | None = None
