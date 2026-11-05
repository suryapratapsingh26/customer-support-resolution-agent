from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Customer, Order, Shipment
from mock_services.shipping.service import (
    ShipmentNotFoundError,
    get_shipment_by_tracking_number,
    get_shipments_by_order_id,
    simulate_shipping_delay,
    update_shipment_status,
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
def test_shipment(db_session):
    customer = Customer(
        name="Test Customer",
        email="shipping@example.com",
    )
    db_session.add(customer)
    db_session.flush()

    order = Order(
        customer_id=customer.id,
        status="shipped",
    )
    db_session.add(order)
    db_session.flush()

    shipment = Shipment(
        order_id=order.id,
        carrier="Test Express",
        tracking_number="TRACK-TEST-001",
        status="processing",
        estimated_delivery_at=datetime.now(timezone.utc)
        + timedelta(days=3),
    )
    db_session.add(shipment)
    db_session.commit()
    db_session.refresh(shipment)

    return shipment


def test_get_shipments_by_order_id(db_session, test_shipment):
    shipments = get_shipments_by_order_id(
        db_session, test_shipment.order_id
    )

    assert len(shipments) == 1
    assert shipments[0].tracking_number == "TRACK-TEST-001"


def test_get_shipment_by_tracking_number(db_session, test_shipment):
    shipment = get_shipment_by_tracking_number(
        db_session, "TRACK-TEST-001"
    )

    assert shipment is not None
    assert shipment.id == test_shipment.id


def test_get_missing_shipment_by_tracking_number(db_session):
    shipment = get_shipment_by_tracking_number(
        db_session, "INVALID-TRACKING"
    )

    assert shipment is None


def test_update_shipment_status_to_shipped(db_session, test_shipment):
    shipment = update_shipment_status(
        db_session,
        "TRACK-TEST-001",
        "shipped",
    )

    assert shipment.status == "shipped"
    assert shipment.shipped_at is not None


def test_update_shipment_status_to_delivered(db_session, test_shipment):
    shipment = update_shipment_status(
        db_session,
        "TRACK-TEST-001",
        "delivered",
    )

    assert shipment.status == "delivered"
    assert shipment.delivered_at is not None


def test_reject_invalid_shipment_status(db_session, test_shipment):
    with pytest.raises(ValueError):
        update_shipment_status(
            db_session,
            "TRACK-TEST-001",
            "unknown_status",
        )


def test_reject_update_for_missing_shipment(db_session):
    with pytest.raises(ShipmentNotFoundError):
        update_shipment_status(
            db_session,
            "INVALID-TRACKING",
            "shipped",
        )


def test_simulate_shipping_delay(db_session, test_shipment):
    original_eta = test_shipment.estimated_delivery_at

    shipment = simulate_shipping_delay(
        db_session,
        "TRACK-TEST-001",
        delay_days=2,
    )

    assert shipment.status == "delayed"
    assert shipment.estimated_delivery_at == (
        original_eta + timedelta(days=2)
    )


def test_reject_zero_day_shipping_delay(db_session, test_shipment):
    with pytest.raises(ValueError):
        simulate_shipping_delay(
            db_session,
            "TRACK-TEST-001",
            delay_days=0,
        )


def test_reject_negative_shipping_delay(db_session, test_shipment):
    with pytest.raises(ValueError):
        simulate_shipping_delay(
            db_session,
            "TRACK-TEST-001",
            delay_days=-1,
        )