import hashlib
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.models import BFFSession, Customer, Order, OrderItem, Payment, Shipment, Ticket
from app.db.session import get_db
from app.main import app
from app.schemas.resolution import KnowledgeSource, ResolutionRecommendation


def _db_session():
    generator = app.dependency_overrides[get_db]()
    return generator, next(generator)


def _session_cookie(client, customer_ids, subject, roles):
    generator, db = _db_session()
    token = f"bff-{subject}-token-value"
    db.add(BFFSession(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), subject=subject,
        roles=roles, customer_ids=customer_ids, csrf_token=f"csrf-{subject}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    db.commit()
    generator.close()
    client.cookies.set(settings.bff_session_cookie_name, token)
    return {"Origin": "http://dashboard.example.test", "X-CSRF-Token": f"csrf-{subject}"}


def _case(customer_name, email, tracking):
    generator, db = _db_session()
    customer = Customer(name=customer_name, email=email)
    db.add(customer)
    db.flush()
    order = Order(customer_id=customer.id, status="delivered")
    db.add(order)
    db.flush()
    db.add(OrderItem(order_id=order.id, product_name="Desk lamp", quantity=1, unit_price=5000))
    ticket = Ticket(customer_id=customer.id, order_id=order.id,
                    subject="Refund for a damaged item", description="The lamp arrived damaged.")
    db.add(ticket)
    db.flush()
    payment = Payment(order_id=order.id, amount=1000, currency="INR", payment_method="card",
                      status="success", transaction_reference=f"transaction-{tracking}")
    shipment = Shipment(order_id=order.id, carrier="Parcel Post", tracking_number=tracking,
                        status="delivered", delivered_at=datetime.now(timezone.utc))
    db.add_all([payment, shipment])
    db.commit()
    ids = customer.id, order.id, ticket.id, payment.id
    generator.close()
    return ids


def test_authenticated_dashboard_refund_workflow_is_customer_scoped(client, monkeypatch):
    monkeypatch.setattr(settings, "agent_api_key", "agent-key-012345678901234567890123456789")
    monkeypatch.setattr(settings, "agent_customer_token_secret", "customer-scope-012345678901234567890123")
    monkeypatch.setattr(settings, "bff_trusted_origins", ["http://dashboard.example.test"])
    customer_id, order_id, ticket_id, payment_id = _case(
        "E2E Customer", "e2e-customer@example.test", "TRACK-E2E-1",
    )
    other_customer_id, _, _, _ = _case("Other Customer", "other-e2e@example.test", "TRACK-E2E-2")
    staff_headers = _session_cookie(
        client, [customer_id], "support-agent-1", ["support_agent", "support_reviewer"],
    )

    context = client.get(
        f"/api/bff/customers/{customer_id}/tickets/{ticket_id}/context",
    )
    assert context.status_code == 200
    assert context.json()["payments"][0]["amount"] == "1000.00"
    assert context.json()["shipments"][0]["tracking_number"] == "TRACK-E2E-1"
    assert "transaction_reference" not in context.text
    assert client.get(f"/api/bff/customers/{other_customer_id}/tickets/{ticket_id}/context").status_code == 404

    recommendation = ResolutionRecommendation(
        ticket_id=ticket_id, issue_category="refund", issue_summary="Damaged item",
        customer_context_summary="Order and payment are available.",
        retrieved_knowledge_sources=[KnowledgeSource(
            id="source-1", document_id="returns", document_name="Returns Policy",
            category="refunds", text="Damaged items require human review.", distance=0.12,
        )], proposed_resolution="Refer the request for review.",
        explanation="A reviewer must confirm the policy evidence.", confidence_score=0.4,
        action_required=True, required_action="refund_approval_review",
    )
    monkeypatch.setattr("app.services.agent_api.run_resolution_workflow", lambda *args, **kwargs: recommendation)
    session = client.post(
        f"/api/bff/customers/{customer_id}/tickets/{ticket_id}/agent-sessions",
        headers=staff_headers, json={"idempotency_key": "e2e-agent-session-1"},
    )
    assert session.status_code == 201
    session_id = session.json()["id"]
    message = client.post(
        f"/api/bff/customers/{customer_id}/agent-sessions/{session_id}/messages",
        headers=staff_headers,
        json={"content": "Please review a refund.", "idempotency_key": "e2e-agent-message-1"},
    )
    assert message.status_code == 200
    execution = message.json()["execution"]
    assert execution["status"] == "waiting_for_approval"
    assert execution["recommendation"]["retrieved_knowledge_sources"][0]["document_name"] == "Returns Policy"
    execution_id = execution["id"]

    request = client.post(
        f"/api/bff/customers/{customer_id}/tickets/{ticket_id}/refund-approvals",
        headers=staff_headers,
        json={"order_id": order_id, "payment_id": payment_id,
              "policy_basis": "price_adjustment", "requested_amount": "25.00",
              "reason": "Customer reports item damage."},
    )
    assert request.status_code == 201
    approval_id = request.json()["id"]
    assert request.json()["requested_by"] == "support-agent-1"
    customer_history = client.get(f"/api/bff/customers/{customer_id}/refund-approvals")
    assert customer_history.status_code == 200
    assert customer_history.json()[0]["status"] == "pending"
    assert client.get(f"/api/bff/customers/{other_customer_id}/refund-approvals").status_code == 404

    self_approval = client.post(
        f"/api/bff/refund-approvals/{approval_id}/approve", headers=staff_headers,
        json={"confirm_policy_review": True},
    )
    assert self_approval.status_code == 409

    reviewer_headers = _session_cookie(client, [], "independent-reviewer", ["support_reviewer"])
    unauthorized = client.post(
        f"/api/bff/refund-approvals/{approval_id}/approve",
        headers={"Origin": reviewer_headers["Origin"], "X-CSRF-Token": "invalid"},
        json={"confirm_policy_review": True},
    )
    assert unauthorized.status_code == 403
    execution_before_approval = client.post(
        f"/api/bff/refund-approvals/{approval_id}/execute", headers=reviewer_headers, json={},
    )
    assert execution_before_approval.status_code == 409
    approved = client.post(
        f"/api/bff/refund-approvals/{approval_id}/approve", headers=reviewer_headers,
        json={"confirm_policy_review": True},
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    duplicate_approval = client.post(
        f"/api/bff/refund-approvals/{approval_id}/approve", headers=reviewer_headers,
        json={"confirm_policy_review": True},
    )
    assert duplicate_approval.status_code == 409
    executed = client.post(f"/api/bff/refund-approvals/{approval_id}/execute", headers=reviewer_headers, json={})
    assert executed.status_code == 200 and executed.json()["status"] == "success"
    resumed = client.post(
        f"/api/bff/agent-executions/{execution_id}/resume", headers=reviewer_headers,
        json={"approval_id": approval_id},
    )
    assert resumed.status_code == 200 and resumed.json()["status"] == "completed"
    assert resumed.json()["approval_id"] == approval_id

    history = client.get("/api/bff/refund-approvals/history")
    assert history.status_code == 200
    record = next(item for item in history.json() if item["id"] == approval_id)
    assert record["status"] == "executed"
    assert record["reviewed_by"] == "independent-reviewer"
    assert record["execution_result"]["refund_id"] == executed.json()["refund_id"]
