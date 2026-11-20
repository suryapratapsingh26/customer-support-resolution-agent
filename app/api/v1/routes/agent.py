from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.agent import require_agent_customer
from app.auth.approval import require_approval_actor
from app.db.models import AgentExecution
from app.db.session import get_db
from app.schemas.agent import (
    AgentConversation,
    AgentExecutionResponse,
    AgentExecutionResume,
    AgentMessageCreate,
    AgentMessageResult,
    AgentSessionCreate,
    AgentSessionResponse,
    AgentSessionStatus,
)
from app.services import agent_api


router = APIRouter(tags=["Customer Support Agent"])


def _raise_http(exc: Exception):
    if isinstance(exc, agent_api.AgentNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, agent_api.AgentConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="Agent operation failed.") from exc


@router.post(
    "/customers/{customer_id}/tickets/{ticket_id}/agent-sessions",
    response_model=AgentSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    customer_id: int,
    ticket_id: int,
    request: AgentSessionCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_customer),
):
    try:
        session, created = agent_api.create_session(
            db, customer_id, ticket_id, request.idempotency_key
        )
        if not created:
            # Returning the ORM object uses the declared schema and stays idempotent.
            return JSONResponse(
                status_code=200,
                content=AgentSessionResponse.model_validate(session).model_dump(mode="json"),
            )
        return session
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)


@router.get(
    "/customers/{customer_id}/agent-sessions/{session_id}",
    response_model=AgentSessionStatus,
)
def get_session(
    customer_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_customer),
):
    try:
        session = agent_api.get_session(db, customer_id, session_id)
        current = db.scalar(select(AgentExecution).where(
            AgentExecution.session_id == session_id,
            AgentExecution.status.in_(("pending", "running", "waiting_for_approval")),
        ).order_by(AgentExecution.id.desc()))
        return AgentSessionStatus(session=session, current_execution=current)
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)


@router.get(
    "/customers/{customer_id}/agent-sessions/{session_id}/messages",
    response_model=AgentConversation,
)
def get_history(
    customer_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_customer),
):
    try:
        session = agent_api.get_session(db, customer_id, session_id)
        return AgentConversation(
            session=session,
            messages=agent_api.get_messages(db, customer_id, session_id),
        )
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)


@router.post(
    "/customers/{customer_id}/agent-sessions/{session_id}/messages",
    response_model=AgentMessageResult,
)
def send_message(
    customer_id: int,
    session_id: int,
    request: AgentMessageCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_customer),
):
    try:
        message, execution, _ = agent_api.send_message(
            db, customer_id, session_id, request.content, request.idempotency_key
        )
        result = AgentMessageResult(message=message, execution=execution)
        if execution.status == "failed":
            raise HTTPException(
                status_code=503,
                detail={"message": "Agent execution failed.", "execution_id": execution.id},
            )
        code = 202 if execution.status == "waiting_for_approval" else 200
        return JSONResponse(status_code=code, content=result.model_dump(mode="json"))
    except HTTPException:
        raise
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)


@router.get(
    "/customers/{customer_id}/agent-executions/{execution_id}",
    response_model=AgentExecutionResponse,
)
def get_execution(
    customer_id: int,
    execution_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_customer),
):
    try:
        return agent_api.get_execution(db, customer_id, execution_id)
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)


@router.get(
    "/customers/{customer_id}/tickets/{ticket_id}/agent-executions",
    response_model=list[AgentExecutionResponse],
)
def list_executions(
    customer_id: int,
    ticket_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_customer),
):
    try:
        return agent_api.list_ticket_executions(db, customer_id, ticket_id)
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)


@router.post(
    "/customers/{customer_id}/agent-executions/{execution_id}/cancel",
    response_model=AgentExecutionResponse,
)
def cancel_execution(
    customer_id: int,
    execution_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_customer),
):
    try:
        return agent_api.cancel_execution(db, customer_id, execution_id)
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)


@router.post(
    "/agent-executions/{execution_id}/resume",
    response_model=AgentExecutionResponse,
)
def resume_execution(
    execution_id: int,
    request: AgentExecutionResume,
    db: Session = Depends(get_db),
    _: str = Depends(require_approval_actor),
):
    try:
        return agent_api.resume_execution_after_approval(db, execution_id, request.approval_id)
    except agent_api.AgentAPIError as exc:
        _raise_http(exc)
    except Exception as exc:
        # Approval/database details are not exposed to the caller.
        raise HTTPException(status_code=503, detail="Execution could not be resumed.") from exc
