from sqlalchemy.orm import configure_mappers

from app.db.base import Base
from app.db.models import Customer, Order, OrderItem, Ticket


def test_all_models_are_registered():
    expected_tables = {
        "customers",
        "orders",
        "order_items",
        "tickets",
    }

    assert set(Base.metadata.tables.keys()) == expected_tables


def test_model_relationships_are_configured():
    configure_mappers()

    assert hasattr(Customer, "orders")
    assert hasattr(Customer, "tickets")
    assert hasattr(Order, "customer")
    assert hasattr(Order, "items")
    assert hasattr(OrderItem, "order")
    assert hasattr(Ticket, "customer")
    assert hasattr(Ticket, "order")