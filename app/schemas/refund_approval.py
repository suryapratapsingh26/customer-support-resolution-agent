from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RefundApprovalCreate(BaseModel):
    order_id: int = Field(gt=0)
    payment_id: int = Field(gt=0)
    policy_basis: Literal[
        "unused_original_packaging", "faulty_item", "incorrect_item",
        "partial_return", "missing_item", "price_adjustment",
    ]
    requested_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=1, max_length=2000)


class RefundRejection(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class RefundApprovalDecision(BaseModel):
    confirm_policy_review: bool


class RefundApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    order_id: int
    payment_id: int
    requested_amount: Decimal
    policy_basis: str
    reason: str
    status: str
    requested_by: str
    policy_review_confirmed: bool
    created_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    executed_at: datetime | None
    refund_id: int | None


class RefundExecutionResult(BaseModel):
    approval: RefundApprovalResponse
    refund_id: int
    payment_id: int
    amount: Decimal
    status: str
    reason: str
    idempotency_key: str
    created_at: datetime
