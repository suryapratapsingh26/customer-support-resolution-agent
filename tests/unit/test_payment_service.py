from decimal import Decimal
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Customer, Order, Payment, Refund, Shipment, Ticket
from app.services import refund_approvals
from mock_services.payments.service import (
    DuplicateRefundError,
    InvalidRefundError,
    get_payments_by_order_id,
    get_refund_history,
    process_refund,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def successful_payment(db_session):
    customer = Customer(name="Test Customer", email="test@example.com")
    db_session.add(customer)
    db_session.flush()
    order = Order(customer_id=customer.id, status="paid")
    db_session.add(order)
    db_session.flush()
    db_session.add(Ticket(customer_id=customer.id, order_id=order.id,
                          subject="Refund", description="Refund request"))
    payment = Payment(order_id=order.id, amount=Decimal("1000.00"), currency="INR",
                      payment_method="card", status="success", transaction_reference="TXN-TEST-001")
    shipment = Shipment(order_id=order.id, carrier="TestCarrier", tracking_number="payment-test-track",
                        status="delivered", delivered_at=datetime.now(timezone.utc) - timedelta(days=1))
    db_session.add_all([payment, shipment])
    db_session.commit()
    db_session.refresh(payment)
    return payment


def approved_request(db, payment, amount, reason):
    ticket = db.scalar(select(Ticket).where(Ticket.order_id == payment.order_id))
    approval = refund_approvals.create_refund_approval(
        db, ticket.id, payment.order_id, payment.id, amount,
        "unused_original_packaging", reason, "request-service"
    )
    return refund_approvals.approve_refund(db, approval.id, "human-reviewer", True)


def execute_for_test(db, payment, amount, reason, key):
    approval = approved_request(db, payment, amount, reason)
    return process_refund(db, payment.id, amount, reason,
                          f"refund-approval-{approval.id}", approval_id=approval.id)


def test_get_payments_by_order_id(db_session, successful_payment):
    payments = get_payments_by_order_id(db_session, successful_payment.order_id)
    assert len(payments) == 1
    assert payments[0].id == successful_payment.id


def test_process_partial_refund_requires_approval_and_succeeds(db_session, successful_payment):
    with pytest.raises(InvalidRefundError, match="approved"):
        process_refund(db_session, successful_payment.id, Decimal("300.00"), "Product issue", "raw")
    refund = execute_for_test(db_session, successful_payment, Decimal("300.00"), "Product issue", "refund-key-001")
    assert refund.amount == Decimal("300.00")
    assert refund.status == "success"


def test_process_full_refund(db_session, successful_payment):
    refund = execute_for_test(db_session, successful_payment, Decimal("1000.00"), "Order cancelled", "refund-key-002")
    assert refund.amount == Decimal("1000.00")


def test_reject_refund_exceeding_payment_amount(db_session, successful_payment):
    ticket = db_session.scalar(select(Ticket).where(Ticket.order_id == successful_payment.order_id))
    with pytest.raises(refund_approvals.RefundEligibilityError):
        refund_approvals.create_refund_approval(
            db_session, ticket.id, successful_payment.order_id, successful_payment.id,
            Decimal("1200.00"), "unused_original_packaging", "Excess refund", "request-service",
        )


def test_reject_zero_refund(db_session, successful_payment):
    ticket = db_session.scalar(select(Ticket).where(Ticket.order_id == successful_payment.order_id))
    with pytest.raises(refund_approvals.RefundEligibilityError):
        refund_approvals.create_refund_approval(
            db_session, ticket.id, successful_payment.order_id, successful_payment.id,
            Decimal("0.00"), "unused_original_packaging", "Invalid amount", "request-service",
        )


def test_idempotency_returns_existing_refund(db_session, successful_payment):
    approval = approved_request(db_session, successful_payment, Decimal("200.00"), "Product issue")
    first = process_refund(db_session, successful_payment.id, Decimal("200.00"),
                           "Product issue", f"refund-approval-{approval.id}", approval_id=approval.id)
    second = process_refund(db_session, successful_payment.id, Decimal("200.00"),
                            "Product issue", f"refund-approval-{approval.id}", approval_id=approval.id)
    assert first.id == second.id
    assert len(get_refund_history(db_session, successful_payment.id)) == 1


def test_reject_reused_idempotency_key_with_different_details(db_session, successful_payment):
    execute_for_test(db_session, successful_payment, Decimal("200.00"), "Product issue", "refund-key-006")
    approval = approved_request(db_session, successful_payment, Decimal("300.00"), "Different reason")
    with pytest.raises(DuplicateRefundError):
        process_refund(db_session, successful_payment.id, Decimal("300.00"),
                       "Different reason", "refund-approval-1", approval_id=approval.id)


def test_reject_refund_for_missing_payment(db_session):
    with pytest.raises(refund_approvals.ApprovalNotFoundError):
        refund_approvals.create_refund_approval(
            db_session, 999, 999, 999, Decimal("100.00"),
            "unused_original_packaging", "Missing payment", "request-service"
        )
