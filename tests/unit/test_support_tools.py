from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Customer, Order, OrderItem, Payment, Shipment, Ticket
from app.tools.support import (
    ToolAccessError,
    check_payment_refund_history,
    check_refund_policy_eligibility,
    lookup_customer_order,
    prepare_shipping_action,
)


@pytest.fixture
def support_records():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        customer = Customer(name="Tool Customer", email="tool@example.test")
        stranger = Customer(name="Other Customer", email="other-tool@example.test")
        db.add_all([customer, stranger])
        db.flush()
        order = Order(customer_id=customer.id, status="shipped")
        other_order = Order(customer_id=stranger.id, status="paid")
        db.add_all([order, other_order])
        db.flush()
        db.add(OrderItem(order_id=order.id, product_name="Speaker", quantity=1, unit_price=100))
        ticket = Ticket(customer_id=customer.id, order_id=order.id,
                        subject="Refund", description="Request")
        payment = Payment(order_id=order.id, amount=Decimal("100.00"), currency="INR",
                          payment_method="card", status="success", transaction_reference="tool-payment")
        shipment = Shipment(order_id=order.id, carrier="ShipCo", tracking_number="tool-track", status="shipped")
        shipment.delivered_at = datetime.now(timezone.utc) - timedelta(days=2)
        shipment.status = "delivered"
        db.add_all([ticket, payment, shipment])
        db.commit()
        yield db, customer, stranger, order, other_order, ticket, payment, shipment
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_tools_validate_ids_and_enforce_customer_order_ownership(support_records):
    db, customer, stranger, order, other_order, ticket, payment, _ = support_records
    assert lookup_customer_order(db, ticket.id, order.id)["order"]["id"] == order.id
    with pytest.raises(ToolAccessError):
        lookup_customer_order(db, ticket.id, other_order.id)
    with pytest.raises(ValidationError):
        lookup_customer_order(db, ticket.id, 0)
    with pytest.raises(ToolAccessError):
        check_refund_policy_eligibility(
            db, ticket.id, order.id, 999, Decimal("10.00"), "unused_original_packaging"
        )


def test_refund_eligibility_tool_applies_delivery_policy_and_requires_human_review(support_records):
    db, _, _, order, _, ticket, payment, _ = support_records
    result = check_refund_policy_eligibility(
        db, ticket.id, order.id, payment.id, Decimal("10.00"), "unused_original_packaging"
    )
    assert result == {
        "eligible_for_execution_review": True,
        "human_policy_review_required": True,
    }


def test_payment_and_refund_tool_returns_history(support_records):
    db, customer, _, order, _, ticket, _, _ = support_records
    result = check_payment_refund_history(db, ticket.id, order.id)
    assert result["payments"][0]["payment"]["status"] == "success"
    assert "amount" not in result["payments"][0]["payment"]
    assert result["payments"][0]["refunds"] == []


def test_shipping_action_is_prepared_but_never_mutated(support_records):
    db, customer, _, order, _, ticket, _, shipment = support_records
    result = prepare_shipping_action(
        db, ticket.id, order.id, shipment.tracking_number, "delayed", "Carrier has not moved the parcel."
    )
    assert result["prepared"] is True
    assert result["executed"] is False
    assert shipment.status == "delivered"
