"""Application services for persistent agent conversations and executions."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.approval_workflow import resume_refund_workflow
from app.agents.workflow import run_resolution_workflow
from app.db.models import AgentExecution, AgentMessage, AgentSession, Customer, Ticket
from app.services import refund_approvals as approval_service
from app.tools.support import ToolAccessError, check_payment_refund_history


class AgentAPIError(Exception):
    pass


class AgentNotFoundError(AgentAPIError):
    pass


class AgentConflictError(AgentAPIError):
    pass


class AgentExecutionError(AgentAPIError):
    pass


TRANSITIONS = {
    "pending": {"running", "cancelled", "failed"},
    "running": {"waiting_for_approval", "completed", "failed", "cancelled"},
    "waiting_for_approval": {"running", "cancelled"},
    "failed": {"running", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _ticket_for_customer(db: Session, ticket_id: int, customer_id: int) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or db.get(Customer, customer_id) is None:
        raise AgentNotFoundError("Ticket or customer was not found.")
    if ticket.customer_id != customer_id:
        raise AgentNotFoundError("Ticket was not found for this customer.")
    return ticket


def create_session(db: Session, customer_id: int, ticket_id: int,
                   idempotency_key: str) -> tuple[AgentSession, bool]:
    _ticket_for_customer(db, ticket_id, customer_id)
    existing = db.scalar(select(AgentSession).where(
        AgentSession.customer_id == customer_id,
        AgentSession.create_idempotency_key == idempotency_key,
    ))
    if existing is not None:
        if existing.ticket_id != ticket_id:
            raise AgentConflictError("Idempotency key was already used for another ticket.")
        return existing, False
    session = AgentSession(
        customer_id=customer_id, ticket_id=ticket_id,
        create_idempotency_key=idempotency_key, status="active",
    )
    try:
        db.add(session)
        db.commit()
        db.refresh(session)
        return session, True
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(AgentSession).where(
            AgentSession.customer_id == customer_id,
            AgentSession.create_idempotency_key == idempotency_key,
        ))
        if existing is not None and existing.ticket_id == ticket_id:
            return existing, False
        raise AgentConflictError("Could not create the agent session.")


def get_session(db: Session, customer_id: int, session_id: int) -> AgentSession:
    session = db.get(AgentSession, session_id)
    if session is None or session.customer_id != customer_id:
        raise AgentNotFoundError("Agent session was not found.")
    _ticket_for_customer(db, session.ticket_id, customer_id)
    return session


def get_messages(db: Session, customer_id: int, session_id: int) -> list[AgentMessage]:
    get_session(db, customer_id, session_id)
    return list(db.scalars(select(AgentMessage).where(
        AgentMessage.session_id == session_id
    ).order_by(AgentMessage.id)).all())


def get_execution(db: Session, customer_id: int, execution_id: int) -> AgentExecution:
    execution = db.get(AgentExecution, execution_id)
    if execution is None:
        raise AgentNotFoundError("Agent execution was not found.")
    session = get_session(db, customer_id, execution.session_id)
    if session.ticket_id != execution.ticket_id:
        raise AgentNotFoundError("Agent execution was not found.")
    return execution


def list_ticket_executions(db: Session, customer_id: int, ticket_id: int) -> list[AgentExecution]:
    _ticket_for_customer(db, ticket_id, customer_id)
    return list(db.scalars(select(AgentExecution).where(
        AgentExecution.ticket_id == ticket_id
    ).order_by(AgentExecution.created_at.desc(), AgentExecution.id.desc())).all())


def _locked_execution(db: Session, execution_id: int) -> AgentExecution:
    execution = db.scalar(select(AgentExecution).where(
        AgentExecution.id == execution_id
    ).with_for_update().execution_options(populate_existing=True))
    if execution is None:
        raise AgentNotFoundError("Agent execution was not found.")
    return execution


def _locked_session(db: Session, customer_id: int, session_id: int) -> AgentSession:
    session = db.scalar(select(AgentSession).where(
        AgentSession.id == session_id
    ).with_for_update().execution_options(populate_existing=True))
    if session is None or session.customer_id != customer_id:
        raise AgentNotFoundError("Agent session was not found.")
    _ticket_for_customer(db, session.ticket_id, customer_id)
    return session


def _apply_transition(execution: AgentExecution, new_status: str) -> None:
    if new_status not in TRANSITIONS.get(execution.status, set()):
        raise AgentConflictError(f"Execution cannot transition from {execution.status} to {new_status}.")
    execution.status = new_status
    execution.updated_at = datetime.now(timezone.utc)


def _append_assistant_message(db: Session, session_id: int, content: str) -> None:
    db.add(AgentMessage(session_id=session_id, role="assistant", content=content))
    session = db.get(AgentSession, session_id)
    if session is not None:
        session.updated_at = datetime.now(timezone.utc)


def _conversation(db: Session, session_id: int) -> list[dict[str, str]]:
    messages = db.scalars(select(AgentMessage).where(
        AgentMessage.session_id == session_id
    ).order_by(AgentMessage.id)).all()
    return [{"role": "customer" if message.role == "customer" else "assistant",
             "content": message.content} for message in messages]


def send_message(
    db: Session, customer_id: int, session_id: int, content: str,
    idempotency_key: str, *, knowledge_service=None, llm=None,
) -> tuple[AgentMessage, AgentExecution, bool]:
    session = _locked_session(db, customer_id, session_id)
    if session.status != "active":
        raise AgentConflictError("Agent session is closed.")
    existing = db.scalar(select(AgentExecution).where(
        AgentExecution.session_id == session_id,
        AgentExecution.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        existing_message = db.get(AgentMessage, existing.message_id)
        if existing_message is None or existing_message.content != content:
            raise AgentConflictError("Idempotency key was already used for another message.")
        return existing_message, existing, False
    active = db.scalar(select(AgentExecution).where(
        AgentExecution.session_id == session_id,
        AgentExecution.status.in_(("pending", "running", "waiting_for_approval")),
    ))
    if active is not None:
        raise AgentConflictError("A session execution is already active.")
    ticket = _ticket_for_customer(db, session.ticket_id, customer_id)
    message = AgentMessage(
        session_id=session_id, role="customer", content=content,
        idempotency_key=idempotency_key,
    )
    try:
        db.add(message)
        db.flush()
        execution = AgentExecution(
            ticket_id=ticket.id, session_id=session.id, message_id=message.id,
            status="pending", idempotency_key=idempotency_key,
        )
        db.add(execution)
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(message)
        db.refresh(execution)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(AgentExecution).where(
            AgentExecution.session_id == session_id,
            AgentExecution.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            existing_message = db.get(AgentMessage, existing.message_id)
            if existing_message is not None and existing_message.content == content:
                return existing_message, existing, False
            raise AgentConflictError("Idempotency key was already used for another message.")
        raise AgentConflictError("Message or execution was already submitted.")

    try:
        execution = _locked_execution(db, execution.id)
        _apply_transition(execution, "running")
        db.commit()
        conversation = _conversation(db, session_id)
        recommendation = run_resolution_workflow(
            ticket.id, db, knowledge_service=knowledge_service, llm=llm,
            conversation_messages=conversation,
        )
        action = None
        waiting = False
        if recommendation.action_required and recommendation.required_action == "refund_approval_review":
            action = {"type": recommendation.required_action,
                      "issue_category": recommendation.issue_category}
            try:
                payment_state = check_payment_refund_history(db, ticket.id, ticket.order_id) if ticket.order_id else None
                waiting = bool(payment_state and any(
                    item["payment"]["status"] == "success" for item in payment_state["payments"]
                ) and not recommendation.missing_information)
            except ToolAccessError:
                waiting = False
        response = f"{recommendation.proposed_resolution}\n\n{recommendation.explanation}"
        if action and not waiting:
            response += " Required order or payment details are not available yet; no refund request was created."
        execution = _locked_execution(db, execution.id)
        if execution.status != "running":
            db.rollback()
            return message, execution, True
        _apply_transition(execution, "waiting_for_approval" if waiting else "completed")
        execution.agent_response = response
        execution.recommendation = recommendation.model_dump(mode="json")
        execution.proposed_action = action
        execution.error_info = None
        _append_assistant_message(db, session_id, response)
        db.commit()
        db.refresh(execution)
        return message, execution, True
    except Exception:
        db.rollback()
        try:
            execution = _locked_execution(db, execution.id)
            if execution.status == "running":
                _apply_transition(execution, "failed")
                execution.error_info = "Agent execution failed. Retry the execution or send a new message."
                db.commit()
            db.refresh(execution)
            return message, execution, True
        except Exception as persistence_error:
            db.rollback()
            raise AgentExecutionError("Agent execution state could not be persisted.") from persistence_error


def cancel_execution(db: Session, customer_id: int, execution_id: int) -> AgentExecution:
    execution = _locked_execution(db, execution_id)
    session = get_session(db, customer_id, execution.session_id)
    if session.ticket_id != execution.ticket_id:
        raise AgentNotFoundError("Agent execution was not found.")
    if execution.approval_id is not None:
        approval = approval_service.get_refund_approval(db, execution.approval_id)
        if approval.status in {"approved", "executed"}:
            raise AgentConflictError("An approved refund execution cannot be cancelled.")
    _apply_transition(execution, "cancelled")
    execution.error_info = None
    db.commit()
    db.refresh(execution)
    return execution


def resume_execution_after_approval(
    db: Session, execution_id: int, approval_id: int,
) -> AgentExecution:
    execution = _locked_execution(db, execution_id)
    if execution.status not in {"waiting_for_approval", "failed", "running"}:
        raise AgentConflictError("Execution is not waiting for a resumable refund approval.")
    resumable_refund = (
        execution.proposed_action is not None
        and execution.proposed_action.get("type") == "refund_approval_review"
    )
    if not resumable_refund and execution.approval_id != approval_id:
        raise AgentConflictError("Execution has no persisted refund review action.")
    approval = approval_service.get_refund_approval(db, approval_id)
    if approval.ticket_id != execution.ticket_id:
        raise AgentNotFoundError("Execution or approval was not found.")
    if execution.approval_id is not None and execution.approval_id != approval_id:
        raise AgentConflictError("Execution is already associated with another approval.")
    if approval.status not in {"approved", "executed"}:
        raise AgentConflictError("Refund approval is not approved.")
    if execution.status != "running":
        _apply_transition(execution, "running")
    execution.approval_id = approval_id
    execution.error_info = None
    db.commit()
    try:
        _, refund = resume_refund_workflow(approval_id, db)
        if refund.status != "success" or approval_service.get_refund_approval(db, approval_id).status != "executed":
            raise AgentExecutionError("Refund execution could not be verified.")
        execution = _locked_execution(db, execution_id)
        if execution.status != "running" or execution.approval_id != approval_id:
            raise AgentConflictError("Execution state changed during refund processing.")
        response = f"The approved refund has been processed successfully. Refund reference: {refund.id}."
        _apply_transition(execution, "completed")
        execution.agent_response = response
        execution.proposed_action = {"type": "refund_execution", "approval_id": approval_id,
                                     "refund_id": refund.id}
        _append_assistant_message(db, execution.session_id, response)
        db.commit()
        db.refresh(execution)
        return execution
    except Exception as exc:
        db.rollback()
        approval = approval_service.get_refund_approval(db, approval_id)
        execution = _locked_execution(db, execution_id)
        if approval.status == "executed" and execution.status == "running":
            # Recover a successful refund if response persistence failed after commit.
            try:
                _, refund = resume_refund_workflow(approval_id, db)
                response = f"The approved refund has been processed successfully. Refund reference: {refund.id}."
                _apply_transition(execution, "completed")
                execution.agent_response = response
                execution.error_info = None
                _append_assistant_message(db, execution.session_id, response)
                db.commit()
                db.refresh(execution)
                return execution
            except Exception:
                db.rollback()
        execution = _locked_execution(db, execution_id)
        if execution.status == "running":
            _apply_transition(execution, "failed")
            execution.error_info = "Approved refund execution failed or could not be confirmed."
            db.commit()
            db.refresh(execution)
        if isinstance(exc, AgentAPIError):
            raise
        raise AgentExecutionError("Approved refund execution failed.") from exc
