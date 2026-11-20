from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import Payment, Refund, RefundApproval


class PaymentNotFoundError(Exception):
    pass


class InvalidRefundError(Exception):
    pass


class DuplicateRefundError(Exception):
    pass


def get_payments_by_order_id(db: Session, order_id: int) -> list[Payment]:
    statement = (
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc())
    )

    return list(db.scalars(statement).all())


def get_payment_by_transaction_reference(
    db: Session, transaction_reference: str
) -> Payment | None:
    statement = select(Payment).where(
        Payment.transaction_reference == transaction_reference
    )

    return db.scalar(statement)


def get_refund_history(db: Session, payment_id: int) -> list[Refund]:
    statement = (
        select(Refund)
        .where(Refund.payment_id == payment_id)
        .order_by(Refund.created_at.desc())
    )

    return list(db.scalars(statement).all())


def process_refund(
    db: Session,
    payment_id: int,
    amount: Decimal,
    reason: str,
    idempotency_key: str,
    *,
    approval_id: int | None = None,
    commit: bool = True,
) -> Refund:
    if approval_id is None:
        raise InvalidRefundError("Refund execution requires an approved refund request.")
    approval = db.scalar(
        select(RefundApproval).where(RefundApproval.id == approval_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        raise InvalidRefundError("Refund approval was not found.")
    if (not approval.policy_review_confirmed or not approval.reviewed_by
            or approval.reviewed_by == approval.requested_by or approval.reviewed_at is None):
        raise InvalidRefundError("Refund approval has no confirmed human policy review.")
    if (approval.payment_id != payment_id or approval.requested_amount != amount
            or approval.reason != reason):
        raise InvalidRefundError("Refund details do not match the approved request.")
    if approval.status == "executed" and approval.refund_id is not None:
        if idempotency_key != f"refund-approval-{approval.id}":
            raise DuplicateRefundError("Idempotency key must be scoped to the approved request.")
        existing = db.get(Refund, approval.refund_id)
        if (existing is None or existing.payment_id != payment_id
                or existing.amount != amount or existing.reason != reason
                or existing.status != "success"
                or existing.idempotency_key != f"refund-approval-{approval.id}"):
            raise InvalidRefundError("Executed approval has no refund record.")
        return existing
    if approval.status != "approved":
        raise InvalidRefundError("Refund execution requires an approved request.")
    if idempotency_key != f"refund-approval-{approval.id}":
        raise DuplicateRefundError("Idempotency key must be scoped to the approved request.")
    if amount <= Decimal("0.00"):
        raise InvalidRefundError("Refund amount must be greater than zero.")

    if not reason.strip():
        raise InvalidRefundError("Refund reason is required.")

    if not idempotency_key.strip():
        raise InvalidRefundError("Idempotency key is required.")

    existing_refund = db.scalar(
        select(Refund).where(Refund.idempotency_key == idempotency_key)
    )

    if existing_refund:
        if (
            existing_refund.payment_id != payment_id
            or existing_refund.amount != amount
            or existing_refund.reason != reason
        ):
            raise DuplicateRefundError(
                "Idempotency key was already used with different refund details."
            )

        raise DuplicateRefundError("Idempotency key is already attached to another refund approval.")

    payment = db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
        .execution_options(populate_existing=True)
    )

    if payment is None:
        raise PaymentNotFoundError(
            f"Payment with ID {payment_id} was not found."
        )

    if payment.status != "success":
        raise InvalidRefundError(
            "Only successful payments can be refunded."
        )

    refunded_amount = db.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.payment_id == payment_id,
            Refund.status == "success",
        )
    )

    remaining_amount = payment.amount - Decimal(str(refunded_amount))

    if amount > remaining_amount:
        raise InvalidRefundError(
            f"Refund amount exceeds the remaining refundable amount "
            f"of {remaining_amount} {payment.currency}."
        )

    refund = Refund(
        payment_id=payment_id,
        amount=amount,
        status="success",
        reason=reason,
        idempotency_key=idempotency_key,
    )

    try:
        db.add(refund)
        db.flush()
        approval.status = "executed"
        approval.refund_id = refund.id
        approval.executed_at = datetime.now(timezone.utc)
        if commit:
            db.commit()
            db.refresh(refund)
        else:
            db.flush()
    except Exception:
        if commit:
            db.rollback()
        raise

    return refund
