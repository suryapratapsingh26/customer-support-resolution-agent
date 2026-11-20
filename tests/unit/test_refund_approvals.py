from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Customer, Order, Payment, Refund, RefundApproval, Shipment, Ticket
from app.agents.approval_workflow import build_refund_execution_workflow
from app.services import refund_approvals as approvals


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def records(db):
    customer = Customer(name="Approval Test", email="approval@example.test")
    db.add(customer)
    db.flush()
    order = Order(customer_id=customer.id, status="paid")
    db.add(order)
    db.flush()
    ticket = Ticket(customer_id=customer.id, order_id=order.id,
                    subject="Refund request", description="Item returned.")
    db.add(ticket)
    db.flush()
    payment = Payment(order_id=order.id, amount=Decimal("100.00"), currency="INR",
                      payment_method="card", status="success", transaction_reference="approval-txn")
    shipment = Shipment(order_id=order.id, carrier="TestCarrier", tracking_number="approval-track",
                        status="delivered", delivered_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add_all([payment, shipment])
    db.commit()
    return customer, order, ticket, payment


def create_request(db, records, amount="40.00"):
    _, order, ticket, payment = records
    return approvals.create_refund_approval(
        db, ticket.id, order.id, payment.id, Decimal(amount), "unused_original_packaging",
        "Verified return", "review-operator"
    )


def test_create_approval_and_prevent_duplicate_active_request(db, records):
    approval = create_request(db, records)
    assert approval.status == "pending"
    assert approval.requested_amount == Decimal("40.00")
    with pytest.raises(approvals.DuplicateApprovalError):
        create_request(db, records, "20.00")


def test_database_rejects_duplicate_active_requests_and_unreviewed_approval_state(db, records):
    approval = create_request(db, records)
    duplicate = RefundApproval(
        ticket_id=approval.ticket_id, order_id=approval.order_id, payment_id=approval.payment_id,
        requested_amount=Decimal("10.00"), policy_basis="unused_original_packaging",
        reason="Second active request", requested_by="request-service", status="pending",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    approval = db.get(RefundApproval, approval.id)
    approval.status = "approved"
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_approve_reject_and_transition_guards(db, records):
    approval = create_request(db, records)
    with pytest.raises(approvals.RefundEligibilityError, match="confirm manual"):
        approvals.approve_refund(db, approval.id, "approver-1", False)
    with pytest.raises(approvals.InvalidApprovalTransitionError, match="cannot approve"):
        approvals.approve_refund(db, approval.id, "review-operator", True)
    approved = approvals.approve_refund(db, approval.id, "approver-1", True)
    assert approved.status == "approved"
    assert approved.reviewed_by == "approver-1"
    assert approved.reviewed_at is not None
    assert approved.policy_review_confirmed is True
    with pytest.raises(approvals.InvalidApprovalTransitionError):
        approvals.reject_refund(db, approval.id, "approver-2", "duplicate")

    # A payment can have only one active request, so rejection is tested on a fresh payment.
    customer, order, ticket, _ = records
    payment2 = Payment(order_id=order.id, amount=Decimal("20.00"), currency="INR",
                       payment_method="card", status="success", transaction_reference="approval-txn-2")
    db.add(payment2)
    db.commit()
    rejected = approvals.create_refund_approval(
        db, ticket.id, order.id, payment2.id, Decimal("10.00"), "unused_original_packaging",
        "Not required", "review-operator"
    )
    rejected = approvals.reject_refund(db, rejected.id, "approver-2", "Policy criteria not met.")
    assert rejected.status == "rejected"
    assert rejected.reviewed_by == "approver-2"
    assert rejected.rejection_reason == "Policy criteria not met."
    with pytest.raises(approvals.InvalidApprovalTransitionError):
        approvals.approve_refund(db, rejected.id, "approver-3", True)


def test_execution_requires_approval_and_repeat_is_idempotent(db, records):
    approval = create_request(db, records)
    with pytest.raises(approvals.InvalidApprovalTransitionError):
        approvals.execute_approved_refund(db, approval.id)
    approvals.approve_refund(db, approval.id, "approver-1", True)
    first_approval, first_refund = approvals.execute_approved_refund(db, approval.id)
    second_approval, second_refund = approvals.execute_approved_refund(db, approval.id)
    assert first_approval.status == second_approval.status == "executed"
    assert first_refund.id == second_refund.id
    assert db.scalar(select(func.count()).select_from(Refund)) == 1


def test_graph_input_cannot_forge_approved_status(db, records):
    approval = create_request(db, records)
    graph = build_refund_execution_workflow(db)
    result = graph.invoke({"approval_id": approval.id, "status": "approved"})
    assert result["status"] == "pending"
    assert result.get("refund") is None
    assert db.scalar(select(func.count()).select_from(Refund)) == 0


def test_rechecks_balance_and_does_not_execute_over_refund(db, records):
    approval = create_request(db, records, "80.00")
    approvals.approve_refund(db, approval.id, "approver-1", True)
    db.add(Refund(payment_id=records[3].id, amount=Decimal("30.00"), status="success",
                  reason="Earlier return", idempotency_key="prior-refund"))
    db.commit()
    with pytest.raises(approvals.RefundEligibilityError):
        approvals.execute_approved_refund(db, approval.id)
    db.expire_all()
    assert db.get(RefundApproval, approval.id).status == "approved"
    assert db.scalar(select(func.count()).select_from(Refund)) == 1


def test_failed_refund_keeps_approval_approved(db, records, monkeypatch):
    approval = create_request(db, records)
    approvals.approve_refund(db, approval.id, "approver-1", True)

    def fail(*args, **kwargs):
        raise RuntimeError("payment processor failed")

    monkeypatch.setattr(approvals, "process_refund", fail)
    with pytest.raises(RuntimeError):
        approvals.execute_approved_refund(db, approval.id)
    db.expire_all()
    assert db.get(RefundApproval, approval.id).status == "approved"
    assert db.scalar(select(func.count()).select_from(Refund)) == 0


def test_commit_failure_rolls_back_refund_and_execution_state(db, records, monkeypatch):
    approval = create_request(db, records)
    approvals.approve_refund(db, approval.id, "approver-1", True)
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
    with pytest.raises(RuntimeError, match="commit failed"):
        approvals.execute_approved_refund(db, approval.id)
    db.expire_all()
    assert db.get(RefundApproval, approval.id).status == "approved"
    assert db.scalar(select(func.count()).select_from(Refund)) == 0


def test_eligibility_rejects_wrong_payment_link_and_over_balance(db, records):
    customer, order, ticket, payment = records
    other_customer = Customer(name="Other", email="other-refund@example.test")
    db.add(other_customer)
    db.flush()
    other_order = Order(customer_id=other_customer.id, status="paid")
    db.add(other_order)
    db.flush()
    other_payment = Payment(order_id=other_order.id, amount=Decimal("20.00"), currency="INR",
                            payment_method="card", status="success", transaction_reference="other-refund-txn")
    other_shipment = Shipment(order_id=other_order.id, carrier="TestCarrier", tracking_number="other-track",
                              status="delivered", delivered_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add_all([other_payment, other_shipment])
    db.commit()
    with pytest.raises(approvals.RefundEligibilityError, match="ticket customer"):
        approvals.check_refund_eligibility(db, ticket.id, other_order.id,
                                           other_payment.id, Decimal("1.00"), "unused_original_packaging")
    other = Payment(order_id=order.id, amount=Decimal("10.00"), currency="INR",
                    payment_method="card", status="failed", transaction_reference="failed-txn")
    db.add(other)
    db.commit()
    with pytest.raises(approvals.RefundEligibilityError):
        approvals.check_refund_eligibility(db, ticket.id, order.id, other.id,
                                           Decimal("1.00"), "unused_original_packaging")
    with pytest.raises(approvals.RefundEligibilityError):
        approvals.check_refund_eligibility(db, ticket.id, order.id, payment.id,
                                           Decimal("101.00"), "unused_original_packaging")
    with pytest.raises(approvals.RefundEligibilityError):
        approvals.check_refund_eligibility(db, ticket.id, order.id, payment.id,
                                           Decimal("1.001"), "unused_original_packaging")


def test_policy_basis_enforces_30_and_90_day_windows(db, records):
    _, order, ticket, payment = records
    delivery = db.scalar(select(Shipment).where(Shipment.order_id == order.id))
    delivery.delivered_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    with pytest.raises(approvals.RefundEligibilityError, match="policy window"):
        approvals.check_refund_eligibility(
            db, ticket.id, order.id, payment.id, Decimal("1.00"), "unused_original_packaging"
        )
    assert approvals.check_refund_eligibility(
        db, ticket.id, order.id, payment.id, Decimal("1.00"), "faulty_item"
    )["human_policy_review_required"] is True
    delivery.delivered_at = datetime.now(timezone.utc) - timedelta(days=91)
    db.commit()
    with pytest.raises(approvals.RefundEligibilityError, match="policy window"):
        approvals.check_refund_eligibility(
            db, ticket.id, order.id, payment.id, Decimal("1.00"), "faulty_item"
        )

