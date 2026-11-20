from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMProviderError, OpenAICompatibleProvider
from app.config import settings
from app.db.models import Customer, Order, Payment, Refund, Shipment, Ticket
from app.knowledge.service import build_knowledge_service
from app.schemas.resolution import KnowledgeSource, ResolutionRecommendation
from app.services.order import get_order
from app.services.ticket import get_ticket


class AgentState(TypedDict, total=False):
    ticket_id: int
    ticket_data: dict[str, Any]
    ticket: dict[str, Any] | None
    context: dict[str, Any]
    analysis: dict[str, Any]
    sources: list[dict[str, Any]]
    recommendation: dict[str, Any]
    error: str | None


class TicketNotFoundError(LookupError):
    pass


class WorkflowError(RuntimeError):
    pass


def _source_records(search_result: dict) -> list[dict[str, Any]]:
    records = []
    for row in search_result.get("results", []):
        metadata = row.get("metadata") or {}
        records.append(KnowledgeSource(
            id=str(row.get("id", "")),
            document_id=metadata.get("document_id"),
            document_name=metadata.get("document_name"),
            category=metadata.get("category"),
            text=str(row.get("text", "")),
            distance=row.get("distance"),
        ).model_dump())
    return records


def build_agent_workflow(db: Session, knowledge_service: Any, llm: Any):
    """Build a single-invocation graph; dependencies are injected for easy testing."""

    def ticket_input(state: AgentState) -> dict:
        supplied = state.get("ticket_data")
        if supplied is not None:
            required = {"id", "customer_id", "subject", "description"}
            if not required.issubset(supplied):
                return {"ticket": None, "error": "invalid_ticket_input"}
            return {"ticket": {"id": int(supplied["id"]),
                                "customer_id": int(supplied["customer_id"]),
                                "order_id": supplied.get("order_id"),
                                "subject": str(supplied["subject"]),
                                "description": str(supplied["description"])}}
        ticket_id = state.get("ticket_id")
        ticket = get_ticket(db, ticket_id) if ticket_id is not None else None
        if ticket is None:
            return {"ticket": None, "error": "ticket_not_found"}
        return {"ticket": {"id": ticket.id, "customer_id": ticket.customer_id,
                            "order_id": ticket.order_id, "subject": ticket.subject,
                            "description": ticket.description}}

    def route_ticket(state: AgentState) -> str:
        return "missing" if state.get("ticket") is None else "context"

    def customer_order_context(state: AgentState) -> dict:
        ticket = state["ticket"]
        customer = db.get(Customer, ticket["customer_id"])
        order = get_order(db, ticket["order_id"]) if ticket.get("order_id") is not None else None
        if order is not None and order.customer_id != ticket["customer_id"]:
            order = None
        order_data = None
        payments, shipments, refunds = [], [], []
        if order is not None:
            order_data = {"id": order.id, "status": order.status,
                          "items": [{"product_name": item.product_name, "quantity": item.quantity}
                                    for item in order.items]}
            payment_rows = list(db.scalars(select(Payment).where(Payment.order_id == order.id)).all())
            # Do not give the LLM monetary values it could use to calculate a refund.
            payments = [{"id": row.id, "currency": row.currency,
                         "payment_method": row.payment_method, "status": row.status} for row in payment_rows]
            for payment in payment_rows:
                for refund in db.scalars(select(Refund).where(Refund.payment_id == payment.id)).all():
                    refunds.append({"status": refund.status, "reason": refund.reason})
            shipments = [{"carrier": row.carrier, "status": row.status,
                          "estimated_delivery_at": row.estimated_delivery_at,
                          "shipped_at": row.shipped_at, "delivered_at": row.delivered_at}
                         for row in db.scalars(select(Shipment).where(Shipment.order_id == order.id)).all()]
        return {"context": {
            "customer": ({"id": customer.id, "name": customer.name} if customer else None),
            "order": order_data, "payments": payments, "refunds": refunds, "shipments": shipments,
        }}

    def analyze_ticket(state: AgentState) -> dict:
        ticket = state["ticket"]
        text = f"{ticket['subject']} {ticket['description']}".casefold()
        categories = {
            "refund": ("refund", "return", "money back"),
            "payment": ("payment", "charged", "charge", "card", "billing"),
            "order_modification": ("change order", "modify order", "cancel order", "update order"),
            "shipping": ("shipping", "delivery", "shipment", "tracking", "arrived", "delayed"),
        }
        category = next((name for name, terms in categories.items() if any(term in text for term in terms)), "general_inquiry")
        missing = []
        if state["context"].get("customer") is None:
            missing.append("Customer record is unavailable.")
        if ticket.get("order_id") is None:
            missing.append("Ticket is not linked to an order.")
        elif state["context"].get("order") is None:
            missing.append("Linked order record is unavailable.")
        return {"analysis": {"category": category, "summary": ticket["subject"], "missing": missing}}

    def retrieve_knowledge(state: AgentState) -> dict:
        ticket = state["ticket"]
        query = f"{ticket['subject']}\n{ticket['description']}"
        service = knowledge_service() if callable(knowledge_service) else knowledge_service
        result = service.search(query)
        return {"sources": _source_records(result)}

    def reason(state: AgentState) -> dict:
        # Refund decisions are intentionally outside the model's remit. Return a
        # fixed review handoff rather than accepting any model-authored eligibility
        # statement or amount, including one expressed without currency symbols.
        if state["analysis"]["category"] == "refund":
            sources = [KnowledgeSource.model_validate(source) for source in state.get("sources", [])]
            references = [source.document_name or source.document_id or source.id for source in sources]
            evidence = ("Retrieved policy sources: " + ", ".join(references) + "."
                        if references else "No relevant policy sources were retrieved.")
            recommendation = ResolutionRecommendation(
                ticket_id=state["ticket"]["id"],
                issue_category="refund",
                issue_summary=state["analysis"]["summary"],
                customer_context_summary=_summarize_context(state["context"]),
                retrieved_knowledge_sources=sources,
                proposed_resolution=("Refer the request for authorized review under applicable policy. "
                                     "This workflow does not determine eligibility or issue a refund."),
                explanation=(evidence + " An authorized reviewer must assess the request and any applicable amount."),
                confidence_score=0.4,
                missing_information=state["analysis"]["missing"],
                human_review_recommended=True,
            )
            return {"recommendation": recommendation.model_dump()}

        payload = {"ticket": state["ticket"], "analysis": state["analysis"],
                   "context": state["context"], "sources": state.get("sources", [])}
        try:
            recommendation = llm.recommend(payload)
        except LLMProviderError as exc:
            raise WorkflowError("LLM provider failed.") from exc
        if not isinstance(recommendation, ResolutionRecommendation):
            try:
                recommendation = ResolutionRecommendation.model_validate(recommendation)
            except Exception as exc:
                raise WorkflowError("LLM returned malformed recommendation data.") from exc
        # Keep trusted identifiers, source metadata, and review policy outside model control.
        recommendation.ticket_id = state["ticket"]["id"]
        recommendation.issue_category = state["analysis"]["category"]
        recommendation.issue_summary = state["analysis"]["summary"]
        recommendation.customer_context_summary = _summarize_context(state["context"])
        recommendation.retrieved_knowledge_sources = [KnowledgeSource.model_validate(s) for s in state.get("sources", [])]
        recommendation.missing_information = sorted(set(recommendation.missing_information + state["analysis"]["missing"]))
        recommendation.human_review_recommended = True
        return {"recommendation": recommendation.model_dump()}

    def structured_response(state: AgentState) -> dict:
        return {"recommendation": ResolutionRecommendation.model_validate(state["recommendation"]).model_dump()}

    graph = StateGraph(AgentState)
    graph.add_node("ticket_input", ticket_input)
    graph.add_node("customer_order_context", customer_order_context)
    graph.add_node("ticket_analysis", analyze_ticket)
    graph.add_node("knowledge_retrieval", retrieve_knowledge)
    graph.add_node("resolution_reasoning", reason)
    graph.add_node("structured_response", structured_response)
    graph.set_entry_point("ticket_input")
    graph.add_conditional_edges("ticket_input", route_ticket,
                                {"missing": END, "context": "customer_order_context"})
    graph.add_edge("customer_order_context", "ticket_analysis")
    graph.add_edge("ticket_analysis", "knowledge_retrieval")
    graph.add_edge("knowledge_retrieval", "resolution_reasoning")
    graph.add_edge("resolution_reasoning", "structured_response")
    graph.add_edge("structured_response", END)
    return graph.compile()


def _summarize_context(context: dict) -> str:
    """Serialize only available context, without inferring missing facts."""
    parts = []
    customer = context.get("customer")
    order = context.get("order")
    if customer:
        parts.append(f"Customer: {customer['name']} (ID {customer['id']}).")
    else:
        parts.append("Customer record unavailable.")
    if order:
        parts.append(f"Order {order['id']} status: {order['status']}; items: {len(order['items'])}.")
    else:
        parts.append("Order information unavailable.")
    parts.append(f"Payments: {len(context.get('payments', []))}; shipments: {len(context.get('shipments', []))}.")
    return " ".join(parts)


def run_resolution_workflow(ticket_id: int | None, db: Session, knowledge_service: Any = None,
                            llm: Any = None, ticket_data: dict[str, Any] | None = None) -> ResolutionRecommendation:
    knowledge_service = knowledge_service or (lambda: build_knowledge_service(settings))
    llm = llm or OpenAICompatibleProvider(settings.llm_api_key, settings.llm_model,
                                          settings.llm_base_url, settings.llm_timeout_seconds)
    graph = build_agent_workflow(db, knowledge_service, llm)
    try:
        result = graph.invoke({"ticket_id": ticket_id, "ticket_data": ticket_data})
    except WorkflowError:
        raise
    except Exception as exc:
        # LangGraph may annotate the original failure with node metadata; keep that
        # detail internal and expose one stable application-level error.
        raise WorkflowError("Resolution workflow failed.") from exc
    if result.get("ticket") is None:
        raise TicketNotFoundError(f"Ticket {ticket_id} was not found.")
    if "recommendation" not in result:
        raise WorkflowError("Workflow did not produce a recommendation.")
    return ResolutionRecommendation.model_validate(result["recommendation"])
