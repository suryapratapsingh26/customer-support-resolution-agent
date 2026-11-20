from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.config import settings
from app.db.models import Customer, Order, Payment, Shipment, Ticket
from app.db.session import get_db
from app.main import app


def seed_refund_case():
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        customer = Customer(name="API Customer", email="api-approval@example.test")
        db.add(customer)
        db.flush()
        order = Order(customer_id=customer.id, status="paid")
        db.add(order)
        db.flush()
        ticket = Ticket(customer_id=customer.id, order_id=order.id,
                        subject="Refund request", description="Returned item")
        db.add(ticket)
        payment = Payment(order_id=order.id, amount=Decimal("100.00"), currency="INR",
                          payment_method="card", status="success", transaction_reference="api-approval-txn")
        shipment = Shipment(order_id=order.id, carrier="API Carrier", tracking_number="api-approval-track",
                            status="delivered", delivered_at=datetime.now(timezone.utc) - timedelta(days=1))
        db.add_all([payment, shipment])
        db.commit()
        return ticket.id, order.id, payment.id
    finally:
        generator.close()


def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "approval_api_key", "review-secret-0123456789-abcdefghijkl")
    monkeypatch.setattr(settings, "approval_actor_id", "configured-reviewer")
    return {"X-Approval-Token": "review-secret-0123456789-abcdefghijkl"}


def request_headers(monkeypatch):
    monkeypatch.setattr(settings, "approval_request_api_key", "request-secret-0123456789-abcdefghijklm")
    monkeypatch.setattr(settings, "approval_request_actor_id", "resolution-agent")
    return {"X-Approval-Request-Token": "request-secret-0123456789-abcdefghijklm"}


def test_approval_api_auth_lifecycle_and_execution_idempotency(client, monkeypatch):
    ticket_id, order_id, payment_id = seed_refund_case()
    path = f"/api/v1/refund-approvals/tickets/{ticket_id}"
    payload = {"order_id": order_id, "payment_id": payment_id,
               "policy_basis": "unused_original_packaging",
               "requested_amount": "25.00", "reason": "Verified return"}
    assert client.post(path, json=payload).status_code == 503  # No request-service identity configured.
    headers = auth_headers(monkeypatch)
    request_auth = request_headers(monkeypatch)
    assert client.post(path, json=payload, headers=headers).status_code == 401
    assert client.post(path, json=payload, headers=request_auth).status_code == 201
    created = client.post(path, json=payload, headers=request_auth)
    assert created.status_code == 409  # Duplicate active approval.

    approval_id = client.get("/api/v1/refund-approvals/pending", headers=headers).json()[0]["id"]
    assert client.post(f"/api/v1/refund-approvals/{approval_id}/execute", headers=headers).status_code == 409
    assert client.post(
        f"/api/v1/refund-approvals/{approval_id}/approve", headers=request_auth,
        json={"confirm_policy_review": True},
    ).status_code == 401
    approved = client.post(f"/api/v1/refund-approvals/{approval_id}/approve", headers=headers, json={"confirm_policy_review": True})
    assert approved.status_code == 200
    assert approved.json()["reviewed_by"] == "configured-reviewer"

    first = client.post(f"/api/v1/refund-approvals/{approval_id}/execute", headers=headers)
    second = client.post(f"/api/v1/refund-approvals/{approval_id}/execute", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["refund_id"] == second.json()["refund_id"]
    assert client.get(f"/api/v1/refund-approvals/{approval_id}/execution", headers=headers).status_code == 200


def test_rejection_and_request_link_validation(client, monkeypatch):
    ticket_id, order_id, payment_id = seed_refund_case()
    headers = auth_headers(monkeypatch)
    request_auth = request_headers(monkeypatch)
    created = client.post(
        f"/api/v1/refund-approvals/tickets/{ticket_id}", headers=request_auth,
        json={"order_id": order_id, "payment_id": payment_id,
              "policy_basis": "unused_original_packaging",
              "requested_amount": "10.00", "reason": "Return"},
    )
    approval_id = created.json()["id"]
    rejected = client.post(
        f"/api/v1/refund-approvals/{approval_id}/reject", headers=headers,
        json={"reason": "Outside policy"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejection_reason"] == "Outside policy"
    assert client.post(f"/api/v1/refund-approvals/{approval_id}/execute", headers=headers).status_code == 409

    mismatch = client.post(
        f"/api/v1/refund-approvals/tickets/{ticket_id}", headers=request_auth,
        json={"order_id": order_id, "payment_id": 999,
              "policy_basis": "unused_original_packaging",
              "requested_amount": "10.00", "reason": "Return"},
    )
    assert mismatch.status_code == 404


def test_approval_endpoints_require_authenticated_operator(client, monkeypatch):
    monkeypatch.setattr(settings, "approval_api_key", None)
    monkeypatch.setattr(settings, "approval_actor_id", None)
    monkeypatch.setattr(settings, "approval_request_api_key", None)
    monkeypatch.setattr(settings, "approval_request_actor_id", None)
    response = client.get("/api/v1/refund-approvals/pending")
    assert response.status_code == 503  # Disabled until operator credentials are configured.


def test_wrong_operator_token_is_rejected(client, monkeypatch):
    auth_headers(monkeypatch)
    request_headers(monkeypatch)
    response = client.get(
        "/api/v1/refund-approvals/pending",
        headers={"X-Approval-Token": "incorrect"},
    )
    assert response.status_code == 401


def test_same_credentials_cannot_configure_both_roles(client, monkeypatch):
    shared_secret = "shared-secret-0123456789-abcdefghijklmnopqrstuvwxyz"
    monkeypatch.setattr(settings, "approval_api_key", shared_secret)
    monkeypatch.setattr(settings, "approval_request_api_key", shared_secret)
    monkeypatch.setattr(settings, "approval_actor_id", "reviewer")
    monkeypatch.setattr(settings, "approval_request_actor_id", "request-service")
    response = client.get(
        "/api/v1/refund-approvals/pending",
        headers={"X-Approval-Token": shared_secret},
    )
    assert response.status_code == 503


def test_execute_unknown_approval_returns_not_found(client, monkeypatch):
    headers = auth_headers(monkeypatch)
    request_headers(monkeypatch)  # Configure the distinct role as required by fail-closed auth.
    response = client.post("/api/v1/refund-approvals/999/execute", headers=headers)
    assert response.status_code == 404

