from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Shipment


class ShipmentNotFoundError(Exception):
    pass


def get_shipments_by_order_id(
    db: Session, order_id: int
) -> list[Shipment]:
    statement = (
        select(Shipment)
        .where(Shipment.order_id == order_id)
        .order_by(Shipment.created_at.desc())
    )

    return list(db.scalars(statement).all())


def get_shipment_by_tracking_number(
    db: Session, tracking_number: str
) -> Shipment | None:
    statement = select(Shipment).where(
        Shipment.tracking_number == tracking_number
    )

    return db.scalar(statement)


def update_shipment_status(
    db: Session,
    tracking_number: str,
    status: str,
    estimated_delivery_at: datetime | None = None,
) -> Shipment:
    shipment = get_shipment_by_tracking_number(db, tracking_number)

    if shipment is None:
        raise ShipmentNotFoundError(
            f"Shipment {tracking_number} was not found."
        )

    allowed_statuses = {
        "processing",
        "shipped",
        "in_transit",
        "out_for_delivery",
        "delivered",
        "delayed",
        "lost",
    }

    if status not in allowed_statuses:
        raise ValueError(f"Unsupported shipment status: {status}")

    now = datetime.now(timezone.utc)

    shipment.status = status

    if estimated_delivery_at is not None:
        shipment.estimated_delivery_at = estimated_delivery_at

    if status == "shipped" and shipment.shipped_at is None:
        shipment.shipped_at = now

    if status == "delivered":
        shipment.delivered_at = now

    db.commit()
    db.refresh(shipment)

    return shipment


def simulate_shipping_delay(
    db: Session,
    tracking_number: str,
    delay_days: int,
) -> Shipment:
    if delay_days <= 0:
        raise ValueError("Delay must be greater than zero days.")

    shipment = get_shipment_by_tracking_number(db, tracking_number)

    if shipment is None:
        raise ShipmentNotFoundError(
            f"Shipment {tracking_number} was not found."
        )

    current_eta = shipment.estimated_delivery_at

    if current_eta is None:
        current_eta = datetime.now(timezone.utc)

    new_eta = current_eta + timedelta(days=delay_days)

    return update_shipment_status(
        db=db,
        tracking_number=tracking_number,
        status="delayed",
        estimated_delivery_at=new_eta,
    )