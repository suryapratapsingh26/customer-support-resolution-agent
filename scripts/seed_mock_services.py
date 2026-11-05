from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Customer, Order, Payment, Refund, Shipment
from app.db.session import SessionLocal


def seed_mock_services() -> None:
    db = SessionLocal()

    try:
        customer_data = [
            ("Aarav Sharma", "aarav@example.com"),
            ("Priya Verma", "priya@example.com"),
            ("Rohan Mehta", "rohan@example.com"),
        ]

        customers = {}

        for name, email in customer_data:
            customer = db.scalar(
                select(Customer).where(Customer.email == email)
            )

            if customer is None:
                customer = Customer(name=name, email=email)
                db.add(customer)
                db.flush()

            customers[email] = customer

        order_data = [
            ("aarav@example.com", "delivered"),
            ("priya@example.com", "shipped"),
            ("rohan@example.com", "processing"),
        ]

        orders = {}

        for email, status in order_data:
            order = db.scalar(
                select(Order)
                .where(Order.customer_id == customers[email].id)
                .order_by(Order.id)
            )

            if order is None:
                order = Order(
                    customer_id=customers[email].id,
                    status=status,
                )
                db.add(order)
                db.flush()

            orders[email] = order

        payment_data = [
            (
                "aarav@example.com",
                Decimal("2499.00"),
                "card",
                "success",
                "TXN-MOCK-001",
            ),
            (
                "priya@example.com",
                Decimal("1599.00"),
                "upi",
                "success",
                "TXN-MOCK-002",
            ),
            (
                "rohan@example.com",
                Decimal("999.00"),
                "card",
                "failed",
                "TXN-MOCK-003",
            ),
        ]

        for email, amount, method, status, reference in payment_data:
            existing = db.scalar(
                select(Payment).where(
                    Payment.transaction_reference == reference
                )
            )

            if existing is None:
                db.add(
                    Payment(
                        order_id=orders[email].id,
                        amount=amount,
                        currency="INR",
                        payment_method=method,
                        status=status,
                        transaction_reference=reference,
                    )
                )

        db.flush()

        payment = db.scalar(
            select(Payment).where(
                Payment.transaction_reference == "TXN-MOCK-001"
            )
        )

        if payment is not None:
            existing_refund = db.scalar(
                select(Refund).where(
                    Refund.idempotency_key == "REFUND-MOCK-001"
                )
            )

            if existing_refund is None:
                db.add(
                    Refund(
                        payment_id=payment.id,
                        amount=Decimal("499.00"),
                        status="success",
                        reason="Partial refund for delayed delivery",
                        idempotency_key="REFUND-MOCK-001",
                    )
                )

        shipment_data = [
            (
                "aarav@example.com",
                "MOCK-TRACK-001",
                "BlueDart",
                "delivered",
                0,
            ),
            (
                "priya@example.com",
                "MOCK-TRACK-002",
                "Delhivery",
                "in_transit",
                2,
            ),
            (
                "rohan@example.com",
                "MOCK-TRACK-003",
                "DTDC",
                "delayed",
                5,
            ),
        ]

        now = datetime.now(timezone.utc)

        for email, tracking, carrier, status, delivery_days in shipment_data:
            existing = db.scalar(
                select(Shipment).where(
                    Shipment.tracking_number == tracking
                )
            )

            if existing is None:
                db.add(
                    Shipment(
                        order_id=orders[email].id,
                        carrier=carrier,
                        tracking_number=tracking,
                        status=status,
                        estimated_delivery_at=now
                        + timedelta(days=delivery_days),
                        shipped_at=now - timedelta(days=2),
                        delivered_at=now if status == "delivered" else None,
                    )
                )

        db.commit()
        print("Mock payment and shipping data seeded successfully.")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_mock_services()