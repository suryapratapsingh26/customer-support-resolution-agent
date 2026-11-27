"""Validate migrations against a disposable, empty PostgreSQL database.

Set MIGRATION_TEST_DATABASE_URL to a dedicated database whose name ends in
`_migration_test`. Refuses existing application tables; never drops a database.
"""
import os
import subprocess
import sys
from urllib.parse import urlsplit

from sqlalchemy import create_engine, inspect


url = os.environ.get("MIGRATION_TEST_DATABASE_URL", "")
parsed = urlsplit(url)
if parsed.scheme != "postgresql+psycopg" or not parsed.hostname:
    raise SystemExit("MIGRATION_TEST_DATABASE_URL must be a PostgreSQL psycopg URL")
if not (parsed.path or "").rstrip("/").endswith("_migration_test"):
    raise SystemExit("Refusing migration validation: database name must end in _migration_test")

os.environ["DATABASE_URL"] = url
engine = create_engine(url, pool_pre_ping=True)
with engine.connect() as conn:
    existing_tables = set(inspect(conn).get_table_names()) - {"alembic_version"}
    if existing_tables:
        raise SystemExit(f"Refusing non-empty migration database; found tables: {sorted(existing_tables)}")


def alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], check=True, env=os.environ.copy())


try:
    alembic("upgrade", "head")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required_tables = {
        "customers", "orders", "order_items", "tickets", "payments", "refunds",
        "shipments", "refund_approvals", "agent_sessions", "agent_messages",
        "agent_executions", "bff_sessions", "bff_login_attempts",
    }
    missing = required_tables - tables
    if missing:
        raise RuntimeError(f"Migration head is missing tables: {sorted(missing)}")

    columns = {column["name"]: column for column in inspector.get_columns("agent_executions")}
    recommendation_type = columns.get("recommendation", {}).get("type")
    if recommendation_type is None or recommendation_type.__class__.__name__.lower() != "json":
        raise RuntimeError("agent_executions.recommendation must use PostgreSQL JSON")

    approval_columns = {column["name"] for column in inspector.get_columns("refund_approvals")}
    if not {"requested_amount", "status", "reviewed_by", "refund_id"} <= approval_columns:
        raise RuntimeError("Refund approval schema is incomplete")
    approval_column_info = {column["name"]: column for column in inspector.get_columns("refund_approvals")}
    amount_type = approval_column_info["requested_amount"]["type"]
    if (amount_type.__class__.__name__.lower() != "numeric"
            or amount_type.precision != 12 or amount_type.scale != 2):
        raise RuntimeError("Refund amount must use NUMERIC(12, 2)")
    timestamp_type = approval_column_info["created_at"]["type"]
    if not getattr(timestamp_type, "timezone", False):
        raise RuntimeError("Approval timestamps must use timezone-aware PostgreSQL types")
    approval_checks = {constraint["name"] for constraint in inspector.get_check_constraints("refund_approvals")}
    if not {"ck_refund_approvals_status", "ck_refund_approvals_amount_positive"} <= approval_checks:
        raise RuntimeError("Refund approval state/amount check constraints are missing")
    indexes = {index["name"] for index in inspector.get_indexes("refund_approvals")}
    if "uq_refund_approvals_active_payment" not in indexes:
        raise RuntimeError("Active refund approval uniqueness index is missing")
    execution_indexes = {index["name"] for index in inspector.get_indexes("agent_executions")}
    if "uq_agent_executions_active_session" not in execution_indexes:
        raise RuntimeError("Active execution uniqueness index is missing")
    required_uniques = {
        "agent_sessions": {"uq_agent_sessions_customer_idempotency"},
        "agent_messages": {"uq_agent_messages_session_idempotency"},
        "agent_executions": {"uq_agent_executions_session_idempotency", "uq_agent_executions_message"},
    }
    for table, expected in required_uniques.items():
        actual = {constraint["name"] for constraint in inspector.get_unique_constraints(table)}
        if not expected <= actual:
            raise RuntimeError(f"Unique constraints missing from {table}: {sorted(expected - actual)}")
    approval_unique_columns = {
        tuple(constraint.get("column_names", []))
        for constraint in inspector.get_unique_constraints("refund_approvals")
    }
    if ("refund_id",) not in approval_unique_columns:
        raise RuntimeError("Refund approval to transaction uniqueness constraint is missing")
    approval_fks = inspector.get_foreign_keys("refund_approvals")
    if not {"tickets", "orders", "payments", "refunds"} <= {
        fk.get("referred_table") for fk in approval_fks
    }:
        raise RuntimeError("Refund approval foreign keys are incomplete")

    alembic("downgrade", "-1")
    downgraded = {column["name"] for column in inspect(engine).get_columns("agent_executions")}
    if "recommendation" in downgraded:
        raise RuntimeError("Latest migration downgrade did not remove recommendation column")
    alembic("upgrade", "head")
    if "recommendation" not in {c["name"] for c in inspect(engine).get_columns("agent_executions")}:
        raise RuntimeError("Latest migration could not be reapplied")
    print("PostgreSQL migration validation passed: empty -> head -> downgrade -1 -> head")
finally:
    engine.dispose()
