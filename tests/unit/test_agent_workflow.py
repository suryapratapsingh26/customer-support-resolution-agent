from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.agents.llm import LLMProviderError
from app.agents.workflow import TicketNotFoundError, WorkflowError, run_resolution_workflow
from app.db.base import Base
from app.db.models import Customer, Order, OrderItem, Payment, Refund, Shipment, Ticket
from app.schemas.resolution import ResolutionRecommendation


class FakeKnowledge:
    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return {"results": [{"id": "chunk-1", "text": "Delivery policy excerpt.",
                             "metadata": {"document_id": "shipping/delivery.md",
                                          "document_name": "delivery.md", "category": "shipping"},
                             "distance": 0.12}]}


class FakeLLM:
    def __init__(self, output=None, error=None):
        self.output, self.error, self.payload = output, error, None

    def recommend(self, payload):
        self.payload = payload
        if self.error:
            raise self.error
        if self.output is not None:
            return self.output
        return ResolutionRecommendation(
            ticket_id=999, issue_category="wrong", issue_summary="wrong",
            customer_context_summary="wrong", retrieved_knowledge_sources=[],
            proposed_resolution="Ask the carrier for an updated delivery estimate.",
            explanation="The available shipment status and delivery policy support checking the estimate.",
            confidence_score=0.82, missing_information=[], human_review_recommended=False,
        )


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed_ticket(db, with_order=True):
    customer = Customer(name="Casey Example", email="casey@example.test")
    db.add(customer)
    db.flush()
    order = None
    if with_order:
        order = Order(customer_id=customer.id, status="shipped")
        db.add(order)
        db.flush()
        db.add(OrderItem(order_id=order.id, product_name="Headphones", quantity=1, unit_price=5000))
    ticket = Ticket(customer_id=customer.id, order_id=order.id if order else None,
                    subject="Delayed delivery", description="Tracking has not updated.")
    db.add(ticket)
    db.commit()
    return ticket, order


def test_successful_workflow_preserves_sources_and_context_and_does_not_mutate(db):
    ticket, order = seed_ticket(db)
    payment = Payment(order_id=order.id, amount=Decimal("5000.00"), currency="INR",
                      payment_method="card", status="captured", transaction_reference="txn-1")
    db.add(payment)
    db.flush()
    db.add(Refund(payment_id=payment.id, amount=Decimal("0.00"), status="none", reason="none",
                  idempotency_key="refund-1"))
    db.add(Shipment(order_id=order.id, carrier="DemoShip", tracking_number="track-1", status="in_transit"))
    db.commit()
    knowledge, llm = FakeKnowledge(), FakeLLM()
    result = run_resolution_workflow(
        ticket.id, db, knowledge, llm,
        conversation_messages=[{"role": "customer", "content": "The tracking page is delayed."}],
    )
    assert result.ticket_id == ticket.id
    assert result.issue_category == "shipping"
    assert result.retrieved_knowledge_sources[0].id == "chunk-1"
    assert result.retrieved_knowledge_sources[0].document_id == "shipping/delivery.md"
    assert "Headphones" in str(llm.payload["context"])
    assert llm.payload["context"]["payments"][0]["status"] == "captured"
    assert "amount" not in llm.payload["context"]["payments"][0]
    assert "unit_price" not in llm.payload["context"]["order"]["items"][0]
    assert llm.payload["context"]["shipments"][0]["status"] == "in_transit"
    assert llm.payload["conversation_history"][0]["content"] == "The tracking page is delayed."
    assert result.human_review_recommended is True
    assert db.scalar(select(func.count()).select_from(Refund)) == 1
    assert db.scalar(select(func.count()).select_from(Payment)) == 1
    assert db.get(Order, order.id).status == "shipped"
    assert db.get(Shipment, 1).status == "in_transit"
    assert db.get(Ticket, ticket.id).status == "open"
    assert len(knowledge.queries) == 1


def test_missing_ticket_takes_terminal_branch_without_llm_or_retrieval(db, monkeypatch):
    knowledge, llm = FakeKnowledge(), FakeLLM()
    monkeypatch.setattr("app.agents.workflow.build_knowledge_service",
                        lambda settings: pytest.fail("knowledge service initialized for missing ticket"))
    with pytest.raises(TicketNotFoundError):
        run_resolution_workflow(999, db, knowledge, llm)
    assert knowledge.queries == []
    assert llm.payload is None


def test_missing_order_payment_and_shipment_are_reported_without_failure(db):
    ticket, _ = seed_ticket(db, with_order=False)
    result = run_resolution_workflow(ticket.id, db, FakeKnowledge(), FakeLLM())
    assert "Ticket is not linked to an order." in result.missing_information
    assert "Order information unavailable." in result.customer_context_summary


def test_structured_ticket_input_can_invoke_workflow(db):
    customer = Customer(name="Structured", email="structured@example.test")
    db.add(customer)
    db.commit()
    result = run_resolution_workflow(
        None, db, FakeKnowledge(), FakeLLM(),
        ticket_data={"id": 17, "customer_id": customer.id, "subject": "General question",
                     "description": "Please explain the warranty."},
    )
    assert result.ticket_id == 17
    assert result.issue_category == "general_inquiry"


def test_provider_failure_becomes_workflow_error(db):
    ticket, _ = seed_ticket(db)
    with pytest.raises(WorkflowError, match="LLM provider"):
        run_resolution_workflow(ticket.id, db, FakeKnowledge(),
                                FakeLLM(error=LLMProviderError("provider unavailable")))


def test_malformed_llm_output_is_rejected(db):
    ticket, _ = seed_ticket(db)
    with pytest.raises(WorkflowError, match="malformed"):
        run_resolution_workflow(ticket.id, db, FakeKnowledge(), FakeLLM(output={"unexpected": True}))


def test_refund_recommendation_uses_fixed_review_handoff_without_calling_llm(db):
    ticket, _ = seed_ticket(db, with_order=False)
    ticket.subject = "Refund request"
    db.commit()
    llm = FakeLLM()
    result = run_resolution_workflow(ticket.id, db, FakeKnowledge(), llm)
    assert llm.payload is None
    assert "authorized review" in result.proposed_resolution
    assert "does not determine eligibility" in result.proposed_resolution
    assert result.human_review_recommended is True
    assert result.action_required is True
    assert result.required_action == "refund_approval_review"

