"""Persistent, human-authorized refund approval and execution services."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Order, Payment, Refund, RefundApproval, Shipment, Ticket
from mock_services.payments.service import (
    InvalidRefundError,
    process_refund,
)


class ApprovalError(Exception):
    pass


class ApprovalNotFoundError(ApprovalError):
    pass


class DuplicateApprovalError(ApprovalError):
    pass


class InvalidApprovalTransitionError(ApprovalError):
    pass


class RefundEligibilityError(ApprovalError):
    pass


def _validate_links(db: Session, ticket_id: int, order_id: int, payment_id: int):
    ticket = db.get(Ticket, ticket_id)
    order = db.get(Order, order_id)
    payment = db.get(Payment, payment_id)
    if ticket is None or order is None or payment is None:
        raise ApprovalNotFoundError("Ticket, order, or payment was not found.")
    if ticket.order_id != order.id or ticket.customer_id != order.customer_id:
        raise RefundEligibilityError("Order does not belong to the ticket customer.")
    if payment.order_id != order.id:
        raise RefundEligibilityError("Payment does not belong to the ticket order.")
    return ticket, order, payment


def check_refund_eligibility(
    db: Session, ticket_id: int, order_id: int, payment_id: int,
    amount: Decimal, policy_basis: str,
) -> dict:
    """Deterministically check payment state and refundable balance.

    Delivery age is checked using the earliest order-level shipment date as a
    conservative proxy. Item-to-shipment linkage, item condition, and return
    receipt are not stored, so a human must still verify policy eligibility.
    """
    try:
        valid_amount = amount.is_finite() and amount > Decimal("0.00")
    except (AttributeError, InvalidOperation):
        valid_amount = False
    if not valid_amount or amount.as_tuple().exponent < -2:
        raise RefundEligibilityError("Refund amount must be positive with at most two decimal places.")
    supported_bases = {
        "unused_original_packaging": 30,
        "faulty_item": 90,
        "incorrect_item": 90,
        "partial_return": None,
        "missing_item": None,
        "price_adjustment": None,
    }
    if policy_basis not in supported_bases:
        raise RefundEligibilityError("Unsupported refund policy basis.")
    _, order, payment = _validate_links(db, ticket_id, order_id, payment_id)
    if payment.status != "success":
        raise RefundEligibilityError("Only successful payments may be refunded.")
    refunded = db.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.payment_id == payment_id, Refund.status == "success"
        )
    )
    remaining = payment.amount - Decimal(str(refunded))
    if amount > remaining:
        raise RefundEligibilityError("Requested amount exceeds the remaining refundable balance.")
    window_days = supported_bases[policy_basis]
    if window_days is not None:
        deliveries = list(db.scalars(
            select(Shipment).where(
                Shipment.order_id == order.id, Shipment.delivered_at.is_not(None)
            ).order_by(Shipment.delivered_at.asc()).with_for_update()
        ).all())
        delivery = deliveries[0].delivered_at if deliveries else None
        if delivery is None:
            raise RefundEligibilityError("A delivery date is required to check the policy window.")
        if delivery.tzinfo is None:
            delivery = delivery.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc).date() - delivery.astimezone(timezone.utc).date()).days
        if age_days < 0 or age_days > window_days:
            raise RefundEligibilityError("Request is outside the applicable refund policy window.")
    return {
        "eligible_for_execution_review": True,
        "remaining_refundable_amount": remaining,
        "currency": payment.currency,
        "policy_basis": policy_basis,
        "human_policy_review_required": True,
    }


def create_refund_approval(
    db: Session, ticket_id: int, order_id: int, payment_id: int,
    amount: Decimal, policy_basis: str, reason: str, requested_by: str,
) -> RefundApproval:
    if not reason or not reason.strip():
        raise RefundEligibilityError("Refund reason is required.")
    if not requested_by or not requested_by.strip():
        raise RefundEligibilityError("Authenticated requester identity is required.")
    check_refund_eligibility(db, ticket_id, order_id, payment_id, amount, policy_basis)
    active = db.scalar(
        select(RefundApproval).where(
            RefundApproval.payment_id == payment_id,
            RefundApproval.status.in_(("pending", "approved")),
        )
    )
    if active:
        raise DuplicateApprovalError("An active approval request already exists for this payment.")
    approval = RefundApproval(
        ticket_id=ticket_id, order_id=order_id, payment_id=payment_id,
        requested_amount=amount, policy_basis=policy_basis,
        reason=reason.strip(), requested_by=requested_by,
        status="pending",
    )
    try:
        db.add(approval)
        db.commit()
        db.refresh(approval)
        return approval
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateApprovalError("An active approval request already exists for this payment.") from exc
    except Exception:
        db.rollback()
        raise


def get_refund_approval(db: Session, approval_id: int) -> RefundApproval:
    approval = db.get(RefundApproval, approval_id)
    if approval is None:
        raise ApprovalNotFoundError("Refund approval was not found.")
    _validate_links(db, approval.ticket_id, approval.order_id, approval.payment_id)
    return approval


def list_pending_refund_approvals(db: Session) -> list[RefundApproval]:
    approvals = list(db.scalars(
        select(RefundApproval).where(RefundApproval.status == "pending")
        .order_by(RefundApproval.created_at, RefundApproval.id)
    ).all())
    for approval in approvals:
        _validate_links(db, approval.ticket_id, approval.order_id, approval.payment_id)
    return approvals


def approve_refund(db: Session, approval_id: int, actor_id: str,
                   policy_review_confirmed: bool = False) -> RefundApproval:
    approval = db.scalar(
        select(RefundApproval).where(RefundApproval.id == approval_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        raise ApprovalNotFoundError("Refund approval was not found.")
    if approval.status != "pending":
        raise InvalidApprovalTransitionError("Only pending approvals can be approved.")
    if actor_id == approval.requested_by:
        raise InvalidApprovalTransitionError("The request creator cannot approve their own request.")
    if not policy_review_confirmed:
        raise RefundEligibilityError("Reviewer must confirm manual refund policy review.")
    check_refund_eligibility(db, approval.ticket_id, approval.order_id,
                             approval.payment_id, approval.requested_amount,
                             approval.policy_basis)
    approval.status = "approved"
    approval.reviewed_by = actor_id
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.policy_review_confirmed = True
    try:
        db.commit()
        db.refresh(approval)
        return approval
    except Exception:
        db.rollback()
        raise


def reject_refund(db: Session, approval_id: int, actor_id: str, rejection_reason: str) -> RefundApproval:
    if not rejection_reason or not rejection_reason.strip():
        raise RefundEligibilityError("Rejection reason is required.")
    approval = db.scalar(
        select(RefundApproval).where(RefundApproval.id == approval_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        raise ApprovalNotFoundError("Refund approval was not found.")
    if approval.status != "pending":
        raise InvalidApprovalTransitionError("Only pending approvals can be rejected.")
    approval.status = "rejected"
    approval.reviewed_by = actor_id
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.rejection_reason = rejection_reason.strip()
    try:
        db.commit()
        db.refresh(approval)
        return approval
    except Exception:
        db.rollback()
        raise


def execute_approved_refund(db: Session, approval_id: int) -> tuple[RefundApproval, Refund]:
    approval = db.scalar(
        select(RefundApproval).where(RefundApproval.id == approval_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        raise ApprovalNotFoundError("Refund approval was not found.")
    if approval.status == "executed" and approval.refund_id is not None:
        refund = db.get(Refund, approval.refund_id)
        if (refund is None or refund.payment_id != approval.payment_id
                or refund.amount != approval.requested_amount or refund.reason != approval.reason
                or refund.status != "success"
                or refund.idempotency_key != f"refund-approval-{approval.id}"):
            raise ApprovalError("Executed approval is missing its refund record.")
        return approval, refund
    if approval.status != "approved":
        raise InvalidApprovalTransitionError("Refund execution requires an approved request.")
    try:
        check_refund_eligibility(db, approval.ticket_id, approval.order_id,
                                 approval.payment_id, approval.requested_amount,
                                 approval.policy_basis)
        refund = process_refund(
            db, approval.payment_id, approval.requested_amount, approval.reason,
            f"refund-approval-{approval.id}", approval_id=approval.id, commit=False,
        )
        approval.status = "executed"
        approval.refund_id = refund.id
        approval.executed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(approval)
        db.refresh(refund)
        return approval, refund
    except InvalidRefundError as exc:
        db.rollback()
        raise RefundEligibilityError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise
