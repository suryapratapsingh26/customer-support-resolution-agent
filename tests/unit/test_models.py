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
        "refund_approvals",
        "shipments",
        "agent_sessions",
        "agent_messages",
        "agent_executions",
    }

    assert set(Base.metadata.tables.keys()) == expected_tables


def test_models_have_expected_tables():
    assert "customers" in Base.metadata.tables
    assert "orders" in Base.metadata.tables
    assert "order_items" in Base.metadata.tables
    assert "tickets" in Base.metadata.tables
    assert "payments" in Base.metadata.tables
    assert "refunds" in Base.metadata.tables
    assert "refund_approvals" in Base.metadata.tables
    assert "shipments" in Base.metadata.tables
    assert "agent_sessions" in Base.metadata.tables
    assert "agent_messages" in Base.metadata.tables
    assert "agent_executions" in Base.metadata.tables
