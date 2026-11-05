from app.db.base import Base
from app.db import models  # noqa: F401


def test_all_models_are_registered():
    expected_tables = {
        "customers",
        "orders",
        "order_items",
        "tickets",
        "payments",
        "refunds",
        "shipments",
    }

    assert set(Base.metadata.tables.keys()) == expected_tables


def test_models_have_expected_tables():
    assert "customers" in Base.metadata.tables
    assert "orders" in Base.metadata.tables
    assert "order_items" in Base.metadata.tables
    assert "tickets" in Base.metadata.tables
    assert "payments" in Base.metadata.tables
    assert "refunds" in Base.metadata.tables
    assert "shipments" in Base.metadata.tables