from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.approval_workflow import resume_refund_workflow
from app.auth.approval import require_approval_actor, require_approval_requester
from app.db.models import Refund
from app.db.session import get_db
from app.schemas.refund_approval import (
    RefundApprovalCreate,
    RefundApprovalResponse,
    RefundExecutionResult,
    RefundApprovalDecision,
    RefundRejection,
)
from app.services import refund_approvals as approval_service


router = APIRouter(prefix="/refund-approvals", tags=["Refund Approvals"])


def _raise_http(exc: Exception):
    if isinstance(exc, approval_service.ApprovalNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, approval_service.DuplicateApprovalError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, approval_service.InvalidApprovalTransitionError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, approval_service.RefundEligibilityError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="Refund approval operation failed.") from exc


def _execution_response(approval, refund):
    return RefundExecutionResult(
        approval=approval,
        refund_id=refund.id,
        payment_id=refund.payment_id,
        amount=refund.amount,
        status=refund.status,
        reason=refund.reason,
        idempotency_key=refund.idempotency_key,
        created_at=refund.created_at,
    )


@router.post("/tickets/{ticket_id}", response_model=RefundApprovalResponse,
             status_code=status.HTTP_201_CREATED)
def create_approval(
    ticket_id: int,
    request: RefundApprovalCreate,
    db: Session = Depends(get_db),
    actor_id: str = Depends(require_approval_requester),
):
    try:
        return approval_service.create_refund_approval(
            db, ticket_id, request.order_id, request.payment_id,
            request.requested_amount, request.policy_basis, request.reason, actor_id,
        )
    except approval_service.ApprovalError as exc:
        _raise_http(exc)


@router.get("/pending", response_model=list[RefundApprovalResponse])
def list_pending(
    db: Session = Depends(get_db),
    actor_id: str = Depends(require_approval_actor),
):
    try:
        return approval_service.list_pending_refund_approvals(db)
    except approval_service.ApprovalError as exc:
        _raise_http(exc)


@router.get("/{approval_id}", response_model=RefundApprovalResponse)
def get_approval(
    approval_id: int,
    db: Session = Depends(get_db),
    actor_id: str = Depends(require_approval_actor),
):
    try:
        return approval_service.get_refund_approval(db, approval_id)
    except approval_service.ApprovalError as exc:
        _raise_http(exc)


@router.post("/{approval_id}/approve", response_model=RefundApprovalResponse)
def approve(
    approval_id: int,
    request: RefundApprovalDecision,
    db: Session = Depends(get_db),
    actor_id: str = Depends(require_approval_actor),
):
    try:
        return approval_service.approve_refund(
            db, approval_id, actor_id, request.confirm_policy_review
        )
    except approval_service.ApprovalError as exc:
        _raise_http(exc)


@router.post("/{approval_id}/reject", response_model=RefundApprovalResponse)
def reject(
    approval_id: int,
    request: RefundRejection,
    db: Session = Depends(get_db),
    actor_id: str = Depends(require_approval_actor),
):
    try:
        return approval_service.reject_refund(db, approval_id, actor_id, request.reason)
    except approval_service.ApprovalError as exc:
        _raise_http(exc)


@router.post("/{approval_id}/execute", response_model=RefundExecutionResult)
def execute(
    approval_id: int,
    db: Session = Depends(get_db),
    actor_id: str = Depends(require_approval_actor),
):
    try:
        approval, refund = resume_refund_workflow(approval_id, db)
        return _execution_response(approval, refund)
    except approval_service.ApprovalError as exc:
        _raise_http(exc)
    except Exception as exc:
        # The transaction service rolls back on errors; do not expose internals.
        raise HTTPException(
            status_code=503,
            detail="Refund execution could not be confirmed; check the approval execution status before retrying.",
        ) from exc


@router.get("/{approval_id}/execution", response_model=RefundExecutionResult)
def get_execution(
    approval_id: int,
    db: Session = Depends(get_db),
    actor_id: str = Depends(require_approval_actor),
):
    try:
        approval = approval_service.get_refund_approval(db, approval_id)
        if approval.status != "executed" or approval.refund_id is None:
            raise HTTPException(status_code=404, detail="Refund execution was not found.")
        refund = db.get(Refund, approval.refund_id)
        if (refund is None or refund.payment_id != approval.payment_id
                or refund.amount != approval.requested_amount
                or refund.reason != approval.reason or refund.status != "success"
                or refund.idempotency_key != f"refund-approval-{approval.id}"):
            raise HTTPException(status_code=404, detail="Refund execution was not found.")
        return _execution_response(approval, refund)
    except approval_service.ApprovalError as exc:
        _raise_http(exc)
