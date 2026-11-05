from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import Payment, Refund


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
) -> Refund:
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

        return existing_refund

    payment = db.get(Payment, payment_id)

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
        db.commit()
        db.refresh(refund)
    except Exception:
        db.rollback()
        raise

    return refund