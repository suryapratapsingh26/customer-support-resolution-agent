from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas.customer import CustomerResponse
from app.schemas.order import OrderResponse
from app.schemas.refund_approval import RefundApprovalResponse
from app.schemas.ticket import TicketResponse


class PaymentRefundContext(BaseModel):
    id: int
    amount: Decimal
    status: str
    reason: str
    created_at: datetime


class PaymentContext(BaseModel):
    id: int
    amount: Decimal
    currency: str
    payment_method: str
    status: str
    created_at: datetime
    refunds: list[PaymentRefundContext]


class ShipmentContext(BaseModel):
    id: int
    carrier: str
    tracking_number: str
    status: str
    estimated_delivery_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None


class TicketContext(BaseModel):
    customer: CustomerResponse
    ticket: TicketResponse
    order: OrderResponse | None
    payments: list[PaymentContext]
    shipments: list[ShipmentContext]


class RefundExecutionSummary(BaseModel):
    refund_id: int
    amount: Decimal
    status: str
    executed_at: datetime


class RefundApprovalHistoryResponse(RefundApprovalResponse):
    customer_id: int
    ticket_subject: str
    execution_result: RefundExecutionSummary | None = None


