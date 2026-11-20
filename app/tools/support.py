"""Validated, read-only support investigation and action-preparation tools."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Payment, Ticket
from app.services import customer as customer_service
from app.services import order as order_service
from app.services import refund_approvals as approval_service
from mock_services.payments.service import get_payments_by_order_id, get_refund_history
from mock_services.shipping.service import get_shipments_by_order_id


class CustomerOrderLookup(BaseModel):
    ticket_id: int = Field(gt=0)
    order_id: int = Field(gt=0)


class RefundEligibilityLookup(CustomerOrderLookup):
    payment_id: int = Field(gt=0)
    policy_basis: Literal[
        "unused_original_packaging", "faulty_item", "incorrect_item",
        "partial_return", "missing_item", "price_adjustment",
    ]
    requested_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class OrderActionPreparation(CustomerOrderLookup):
    action: Literal["cancel", "modify"]
    details: str = Field(min_length=1, max_length=1000)


class ShippingActionPreparation(CustomerOrderLookup):
    tracking_number: str = Field(min_length=1, max_length=100)
    proposed_status: Literal["delayed", "lost", "out_for_delivery", "delivered"]
    rationale: str = Field(min_length=1, max_length=1000)


class ToolAccessError(ValueError):
    pass


def _owned_order(db: Session, ticket_id: int, order_id: int):
    lookup = CustomerOrderLookup(ticket_id=ticket_id, order_id=order_id)
    ticket = db.get(Ticket, lookup.ticket_id)
    if ticket is None:
        raise ToolAccessError("Ticket was not found.")
    if ticket.order_id != lookup.order_id:
        raise ToolAccessError("Order does not belong to the specified ticket.")
    customer = customer_service.get_customer(db, ticket.customer_id)
    if customer is None:
        raise ToolAccessError("Customer was not found.")
    order = order_service.get_order(db, lookup.order_id)
    if order is None:
        raise ToolAccessError("Order was not found.")
    if order.customer_id != customer.id:
        raise ToolAccessError("Order does not belong to the specified customer.")
    return ticket, customer, order


def lookup_customer_order(db: Session, ticket_id: int, order_id: int) -> dict:
    ticket, customer, order = _owned_order(db, ticket_id, order_id)
    return {
        "ticket_id": ticket.id,
        "customer": {"id": customer.id, "name": customer.name},
        "order": {"id": order.id, "status": order.status,
                  "items": [{"id": item.id, "product_name": item.product_name,
                             "quantity": item.quantity} for item in order.items]},
    }


def check_payment_refund_history(db: Session, ticket_id: int, order_id: int) -> dict:
    _, _, order = _owned_order(db, ticket_id, order_id)
    result = []
    for payment in get_payments_by_order_id(db, order.id):
        result.append({
            "payment": {"id": payment.id, "currency": payment.currency,
                        "payment_method": payment.payment_method,
                        "status": payment.status},
            "refunds": [{"id": refund.id, "status": refund.status, "reason": refund.reason}
                        for refund in get_refund_history(db, payment.id)],
        })
    return {"order_id": order.id, "payments": result}


def retrieve_shipment_status(db: Session, ticket_id: int, order_id: int) -> dict:
    _, _, order = _owned_order(db, ticket_id, order_id)
    shipments = get_shipments_by_order_id(db, order.id)
    return {"order_id": order.id, "shipments": [
        {"carrier": shipment.carrier, "tracking_number": shipment.tracking_number,
         "status": shipment.status, "estimated_delivery_at": shipment.estimated_delivery_at,
         "shipped_at": shipment.shipped_at, "delivered_at": shipment.delivered_at}
        for shipment in shipments
    ]}


def check_refund_policy_eligibility(
    db: Session, ticket_id: int, order_id: int,
    payment_id: int, requested_amount: Decimal, policy_basis: str,
) -> dict:
    request = RefundEligibilityLookup(ticket_id=ticket_id, order_id=order_id, payment_id=payment_id,
                                      policy_basis=policy_basis,
                                      requested_amount=requested_amount)
    ticket, _, order = _owned_order(db, ticket_id, order_id)
    payment = db.get(Payment, request.payment_id)
    if payment is None or payment.order_id != order.id:
        raise ToolAccessError("Payment does not belong to the specified order.")
    # The service checks deterministic payment state and remaining balance. It
    # deliberately returns a human policy review requirement for missing evidence.
    result = approval_service.check_refund_eligibility(
        db, ticket_id=ticket.id, order_id=order.id, payment_id=payment.id,
        amount=request.requested_amount, policy_basis=request.policy_basis,
    )
    return {"eligible_for_execution_review": result["eligible_for_execution_review"],
            "human_policy_review_required": result["human_policy_review_required"]}


def prepare_order_action(db: Session, ticket_id: int, order_id: int,
                         action: str, details: str) -> dict:
    request = OrderActionPreparation(ticket_id=ticket_id, order_id=order_id,
                                     action=action, details=details)
    _, _, order = _owned_order(db, request.ticket_id, request.order_id)
    return {"prepared": False, "supported": False, "order_id": order.id,
            "action": request.action,
            "reason": "No order mutation service is currently available; no change was made."}


def prepare_shipping_action(db: Session, ticket_id: int, order_id: int,
                            tracking_number: str, proposed_status: str,
                            rationale: str) -> dict:
    request = ShippingActionPreparation(ticket_id=ticket_id, order_id=order_id,
                                        tracking_number=tracking_number,
                                        proposed_status=proposed_status, rationale=rationale)
    _, _, order = _owned_order(db, request.ticket_id, request.order_id)
    shipment = next((s for s in get_shipments_by_order_id(db, order.id)
                     if s.tracking_number == request.tracking_number), None)
    if shipment is None:
        raise ToolAccessError("Shipment does not belong to the specified order.")
    return {"prepared": True, "executed": False, "order_id": order.id,
            "tracking_number": shipment.tracking_number,
            "current_status": shipment.status, "proposed_status": request.proposed_status,
            "rationale": request.rationale}
