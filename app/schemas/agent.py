from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.resolution import ResolutionRecommendation


class AgentSessionCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class AgentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    customer_id: int
    status: Literal["active", "closed"]
    created_at: datetime
    updated_at: datetime


class AgentMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: Literal["customer", "assistant"]
    content: str
    created_at: datetime


class AgentExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    session_id: int
    status: Literal[
        "pending", "running", "waiting_for_approval", "completed", "failed", "cancelled",
    ]
    agent_response: str | None
    recommendation: ResolutionRecommendation | None = None
    proposed_action: dict | None
    approval_id: int | None
    error_info: str | None
    created_at: datetime
    updated_at: datetime


class AgentSessionStatus(BaseModel):
    session: AgentSessionResponse
    current_execution: AgentExecutionResponse | None = None


class AgentMessageResult(BaseModel):
    message: AgentMessageResponse
    execution: AgentExecutionResponse


class AgentConversation(BaseModel):
    session: AgentSessionResponse
    messages: list[AgentMessageResponse]


class AgentExecutionResume(BaseModel):
    approval_id: int = Field(gt=0)
