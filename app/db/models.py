from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    CheckConstraint,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="order")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[int] = mapped_column(nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="open", nullable=False
    )

    customer: Mapped["Customer"] = relationship(back_populates="tickets")
    order: Mapped["Order | None"] = relationship(back_populates="tickets")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), default="INR", nullable=False
    )
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_reference: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship(back_populates="payments")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="payment")


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    payment: Mapped["Payment"] = relationship(back_populates="refunds")


class RefundApproval(Base):
    __tablename__ = "refund_approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executed')",
            name="ck_refund_approvals_status",
        ),
        CheckConstraint("requested_amount > 0", name="ck_refund_approvals_amount_positive"),
        CheckConstraint(
            "policy_basis IN ('unused_original_packaging', 'faulty_item', 'incorrect_item', "
            "'partial_return', 'missing_item', 'price_adjustment')",
            name="ck_refund_approvals_policy_basis",
        ),
        CheckConstraint(
            "status != 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND policy_review_confirmed = true AND reviewed_by != requested_by)",
            name="ck_refund_approvals_approved_review",
        ),
        CheckConstraint(
            "status != 'rejected' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND rejection_reason IS NOT NULL AND length(trim(rejection_reason)) > 0 "
            "AND reviewed_by != requested_by)",
            name="ck_refund_approvals_rejected_review",
        ),
        CheckConstraint(
            "status != 'executed' OR (refund_id IS NOT NULL AND executed_at IS NOT NULL "
            "AND policy_review_confirmed = true AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND reviewed_by != requested_by)",
            name="ck_refund_approvals_executed_refund",
        ),
        CheckConstraint(
            "status != 'pending' OR (reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND rejection_reason IS NULL AND executed_at IS NULL AND refund_id IS NULL "
            "AND policy_review_confirmed = false)",
            name="ck_refund_approvals_pending_unreviewed",
        ),
        Index(
            "uq_refund_approvals_active_payment",
            "payment_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'approved')"),
            postgresql_where=text("status IN ('pending', 'approved')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), nullable=False)
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    policy_basis: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_review_confirmed: Mapped[bool] = mapped_column(default=False, server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_id: Mapped[int | None] = mapped_column(ForeignKey("refunds.id"), unique=True, nullable=True)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="ck_agent_sessions_status"),
        UniqueConstraint("customer_id", "create_idempotency_key", name="uq_agent_sessions_customer_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    create_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint("role IN ('customer', 'assistant')", name="ck_agent_messages_role"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_agent_messages_session_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting_for_approval', 'completed', 'failed', 'cancelled')",
            name="ck_agent_executions_status",
        ),
        UniqueConstraint("session_id", "idempotency_key", name="uq_agent_executions_session_idempotency"),
        UniqueConstraint("message_id", name="uq_agent_executions_message"),
        Index(
            "uq_agent_executions_active_session", "session_id", unique=True,
            sqlite_where=text("status IN ('pending', 'running', 'waiting_for_approval')"),
            postgresql_where=text("status IN ('pending', 'running', 'waiting_for_approval')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("agent_messages.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_action: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("refund_approvals.id"), nullable=True)
    error_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BFFLoginAttempt(Base):
    __tablename__ = "bff_login_attempts"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BFFSession(Base):
    __tablename__ = "bff_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    customer_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False
    )
    carrier: Mapped[str] = mapped_column(String(100), nullable=False)
    tracking_number: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    estimated_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship(back_populates="shipments")
