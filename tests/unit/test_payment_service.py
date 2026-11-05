from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Customer, Order, Payment, Refund
from mock_services.payments.service import (
    DuplicateRefundError,
    InvalidRefundError,
    PaymentNotFoundError,
    get_payments_by_order_id,
    get_refund_history,
    process_refund,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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

    payment = Payment(
        order_id=order.id,
        amount=Decimal("1000.00"),
        currency="INR",
        payment_method="card",
        status="success",
        transaction_reference="TXN-TEST-001",
    )
    db_session.add(payment)
    db_session.commit()
    db_session.refresh(payment)

    return payment


def test_get_payments_by_order_id(db_session, successful_payment):
    payments = get_payments_by_order_id(
        db_session, successful_payment.order_id
    )

    assert len(payments) == 1
    assert payments[0].id == successful_payment.id


def test_process_partial_refund(db_session, successful_payment):
    refund = process_refund(
        db=db_session,
        payment_id=successful_payment.id,
        amount=Decimal("300.00"),
        reason="Product issue",
        idempotency_key="refund-key-001",
    )

    assert refund.amount == Decimal("300.00")
    assert refund.status == "success"


def test_process_full_refund(db_session, successful_payment):
    refund = process_refund(
        db=db_session,
        payment_id=successful_payment.id,
        amount=Decimal("1000.00"),
        reason="Order cancelled",
        idempotency_key="refund-key-002",
    )

    assert refund.amount == Decimal("1000.00")


def test_reject_refund_exceeding_payment_amount(
    db_session, successful_payment
):
    with pytest.raises(InvalidRefundError):
        process_refund(
            db=db_session,
            payment_id=successful_payment.id,
            amount=Decimal("1200.00"),
            reason="Excess refund",
            idempotency_key="refund-key-003",
        )


def test_reject_zero_refund(db_session, successful_payment):
    with pytest.raises(InvalidRefundError):
        process_refund(
            db=db_session,
            payment_id=successful_payment.id,
            amount=Decimal("0.00"),
            reason="Invalid amount",
            idempotency_key="refund-key-004",
        )


def test_idempotency_returns_existing_refund(
    db_session, successful_payment
):
    first_refund = process_refund(
        db_session,
        successful_payment.id,
        Decimal("200.00"),
        "Product issue",
        "refund-key-005",
    )

    second_refund = process_refund(
        db_session,
        successful_payment.id,
        Decimal("200.00"),
        "Product issue",
        "refund-key-005",
    )

    assert first_refund.id == second_refund.id
    assert len(get_refund_history(db_session, successful_payment.id)) == 1


def test_reject_reused_idempotency_key_with_different_details(
    db_session, successful_payment
):
    process_refund(
        db_session,
        successful_payment.id,
        Decimal("200.00"),
        "Product issue",
        "refund-key-006",
    )

    with pytest.raises(DuplicateRefundError):
        process_refund(
            db_session,
            successful_payment.id,
            Decimal("300.00"),
            "Different reason",
            "refund-key-006",
        )


def test_reject_refund_for_missing_payment(db_session):
    with pytest.raises(PaymentNotFoundError):
        process_refund(
            db_session,
            payment_id=999,
            amount=Decimal("100.00"),
            reason="Missing payment",
            idempotency_key="refund-key-007",
        )