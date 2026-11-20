from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import AgentExecution, AgentMessage, Customer, Order, Ticket
from app.schemas.resolution import KnowledgeSource, ResolutionRecommendation
from app.services import agent_api


def database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    customer = Customer(name="Casey", email="casey@example.test")
    db.add(customer)
    db.flush()
    order = Order(customer_id=customer.id, status="shipped")
    db.add(order)
    db.flush()
    ticket = Ticket(customer_id=customer.id, order_id=order.id,
                    subject="Shipping update", description="Where is my order?")
    db.add(ticket)
    db.commit()
    return engine, db, customer, ticket


def test_session_and_message_idempotency_and_ownership(monkeypatch):
    engine, db, customer, ticket = database()
    try:
        session, created = agent_api.create_session(db, customer.id, ticket.id, "session-key-001")
        same_session, created_again = agent_api.create_session(db, customer.id, ticket.id, "session-key-001")
        assert created and not created_again and same_session.id == session.id

        recommendation = ResolutionRecommendation(
            ticket_id=ticket.id, issue_category="shipping", issue_summary=ticket.subject,
            customer_context_summary="Order is available.",
            retrieved_knowledge_sources=[KnowledgeSource(
                id="source-1", document_id="shipping-policy", document_name="Shipping Policy",
                category="shipping", text="Delivery updates can take one business day.", distance=0.1,
            )], proposed_resolution="Check shipment status.",
            explanation="The order is available.", confidence_score=0.8,
        )

        monkeypatch.setattr(agent_api, "run_resolution_workflow", lambda *a, **k: recommendation)
        msg, execution, processed = agent_api.send_message(
            db, customer.id, session.id, "Please check this order", "message-key-001"
        )
        duplicate, same_execution, processed_again = agent_api.send_message(
            db, customer.id, session.id, "Please check this order", "message-key-001"
        )
        assert processed and not processed_again
        assert duplicate.id == msg.id and same_execution.id == execution.id
        assert execution.status == "completed"
        assert execution.recommendation["retrieved_knowledge_sources"][0]["document_name"] == "Shipping Policy"
        assert len(agent_api.get_messages(db, customer.id, session.id)) == 2
        assert len(agent_api.list_ticket_executions(db, customer.id, ticket.id)) == 1

        try:
            agent_api.get_session(db, customer.id + 1, session.id)
        except agent_api.AgentNotFoundError:
            pass
        else:
            raise AssertionError("cross-customer session access was allowed")
        assert db.scalar(select(AgentMessage).where(AgentMessage.role == "assistant")).content
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_workflow_failure_is_persisted_and_can_be_cancelled(monkeypatch):
    engine, db, customer, ticket = database()
    try:
        session, _ = agent_api.create_session(db, customer.id, ticket.id, "session-key-002")
        monkeypatch.setattr(agent_api, "run_resolution_workflow", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
        _, execution, _ = agent_api.send_message(
            db, customer.id, session.id, "Help", "message-key-002"
        )
        assert execution.status == "failed"
        assert execution.error_info == "Agent execution failed. Retry the execution or send a new message."
        cancelled = agent_api.cancel_execution(db, customer.id, execution.id)
        assert cancelled.status == "cancelled"
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_refund_handoff_waits_without_creating_or_executing_refund(monkeypatch):
    engine, db, customer, ticket = database()
    try:
        session, _ = agent_api.create_session(db, customer.id, ticket.id, "session-key-003")

        recommendation = ResolutionRecommendation(
            ticket_id=ticket.id, issue_category="refund", issue_summary=ticket.subject,
            customer_context_summary="Order is available.", retrieved_knowledge_sources=[],
            proposed_resolution="Send for review.", explanation="A human reviewer is required.",
            confidence_score=0.4, action_required=True,
            required_action="refund_approval_review",
        )

        monkeypatch.setattr(agent_api, "run_resolution_workflow", lambda *a, **k: recommendation)
        monkeypatch.setattr(agent_api, "check_payment_refund_history", lambda *a: {"payments": [{"payment": {"status": "success"}}]})
        _, execution, _ = agent_api.send_message(
            db, customer.id, session.id, "I want a refund", "message-key-003"
        )
        assert execution.status == "waiting_for_approval"
        assert execution.approval_id is None
        assert db.scalar(select(AgentExecution)).status == "waiting_for_approval"
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_resume_cannot_attach_approval_to_unrelated_execution():
    engine, db, customer, ticket = database()
    try:
        session, _ = agent_api.create_session(db, customer.id, ticket.id, "session-key-004")
        message = AgentMessage(session_id=session.id, role="customer", content="Where is it?")
        db.add(message)
        db.flush()
        execution = AgentExecution(
            ticket_id=ticket.id, session_id=session.id, message_id=message.id,
            status="running", idempotency_key="message-key-004",
        )
        db.add(execution)
        db.commit()
        try:
            agent_api.resume_execution_after_approval(db, execution.id, 123)
        except agent_api.AgentConflictError as exc:
            assert "no persisted refund review action" in str(exc)
        else:
            raise AssertionError("unrelated execution accepted a refund approval")
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
