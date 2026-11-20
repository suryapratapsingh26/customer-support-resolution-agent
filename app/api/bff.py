"""Same-origin, cookie-authenticated API for the support dashboard."""
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.agent import create_customer_scope_token
from app.auth.oidc import OIDCError, begin_login, complete_login, cookie_options, session_from_request
from app.config import settings
from app.db.models import BFFSession, Customer, Ticket
from app.db.session import get_db
from app.schemas.agent import (
    AgentConversation, AgentExecutionResponse,
    AgentExecutionResume, AgentMessageCreate, AgentMessageResult, AgentSessionCreate,
    AgentSessionResponse, AgentSessionStatus,
)
from app.schemas.refund_approval import (
    RefundApprovalCreate, RefundApprovalDecision, RefundApprovalResponse,
    RefundExecutionResult, RefundRejection,
)
from app.schemas.dashboard import (
    PaymentContext, PaymentRefundContext, RefundApprovalHistoryResponse,
    RefundExecutionSummary, ShipmentContext, TicketContext,
)
from app.services import agent_api
from app.services import refund_approvals
from app.services import customer as customer_service
from app.services import order as order_service
from app.services import ticket as ticket_service
from app.tools.support import ToolAccessError, lookup_customer_order
from mock_services.payments.service import get_payments_by_order_id, get_refund_history
from mock_services.shipping.service import get_shipments_by_order_id


router = APIRouter(prefix="/api/bff", tags=["Dashboard BFF"])


def require_user(request: Request, db: Session = Depends(get_db)) -> BFFSession:
    session = session_from_request(request, db)
    if session is None:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    return session


def require_reviewer(session: BFFSession = Depends(require_user)) -> BFFSession:
    if settings.oidc_reviewer_role not in session.roles:
        raise HTTPException(status_code=403, detail="Reviewer access required.")
    return session


def _customer(session: BFFSession, customer_id: int) -> int:
    if customer_id not in session.customer_ids:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return customer_id


def _origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in {item.rstrip("/") for item in settings.bff_trusted_origins}:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    session: BFFSession = Depends(require_user),
) -> BFFSession:
    import secrets

    _origin(request)
    token = request.headers.get("x-csrf-token") or x_csrf_token
    if not token or not secrets.compare_digest(token, session.csrf_token):
        raise HTTPException(status_code=403, detail="Request verification failed.")
    return session


async def _agent_call(request: Request, customer_id: int, method: str, path: str,
                      body: dict | None = None) -> object:
    if not settings.agent_api_key or not settings.agent_customer_token_secret:
        raise HTTPException(status_code=503, detail="Agent service is not configured.")
    headers = {
        "X-Agent-API-Key": settings.agent_api_key,
        "X-Agent-Customer-Token": create_customer_scope_token(
            customer_id, expires_at=int(datetime.now(timezone.utc).timestamp()) + 300,
        ),
    }
    try:
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
            result = await client.request(method, f"/api/v1{path}", json=body, headers=headers)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent service is temporarily unavailable.") from exc
    if not result.is_success:
        messages = {404: "Resource not found.", 409: "The operation conflicts with the current state.",
                    422: "The request was invalid.", 503: "Agent service is temporarily unavailable."}
        code = result.status_code if result.status_code in messages else 503
        raise HTTPException(status_code=code, detail=messages[code])
    return result.json()


def _ticket(db: Session, session: BFFSession, ticket_id: int, customer_id: int) -> Ticket:
    _customer(session, customer_id)
    ticket = ticket_service.get_ticket(db, ticket_id)
    if ticket is None or ticket.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return ticket


@router.get("/auth/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    session = session_from_request(request, db)
    if session is None:
        return {"authenticated": False, "user": None,
                "permissions": {"reviewer": False, "agent": False}}
    return {
        "authenticated": True,
        "user": {"subject": session.subject, "name": session.display_name, "email": session.email},
        "permissions": {
            "reviewer": settings.oidc_reviewer_role in session.roles,
            "agent": settings.oidc_agent_role in session.roles,
        },
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at,
    }


@router.get("/auth/login")
async def login(db: Session = Depends(get_db)):
    try:
        location, browser_binding = await begin_login(db)
        response = RedirectResponse(location, status_code=303)
        response.set_cookie(
            key="bff_oidc_binding", value=browser_binding, httponly=True,
            secure=settings.bff_session_cookie_secure, samesite="lax", path="/api/bff/auth/callback",
            max_age=300,
        )
        return response
    except HTTPException:
        raise
    except OIDCError as exc:
        raise HTTPException(status_code=503, detail="Sign-in is temporarily unavailable.") from exc


@router.get("/auth/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                   db: Session = Depends(get_db)):
    if error or not code or not state:
        raise HTTPException(status_code=401, detail="Sign-in could not be completed.")
    try:
        _, raw_session = await complete_login(db, code, state, request.cookies.get("bff_oidc_binding"))
    except OIDCError as exc:
        raise HTTPException(status_code=401, detail="Sign-in could not be completed.") from exc
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(value=raw_session, **cookie_options())
    response.delete_cookie("bff_oidc_binding", path="/api/bff/auth/callback",
                           httponly=True, secure=settings.bff_session_cookie_secure, samesite="lax")
    return response


@router.post("/auth/logout")
def logout(request: Request,
           session: BFFSession = Depends(require_csrf), db: Session = Depends(get_db)):
    db.delete(session)
    db.commit()
    result = Response(status_code=204)
    result.delete_cookie(settings.bff_session_cookie_name, path="/", httponly=True,
                         secure=settings.bff_session_cookie_secure, samesite="lax")
    return result


@router.get("/customers")
def customers(session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    if not session.customer_ids:
        return []
    rows = db.scalars(select(Customer).where(Customer.id.in_(session.customer_ids)).order_by(Customer.name)).all()
    return [{"id": row.id, "name": row.name, "email": row.email} for row in rows]


@router.get("/customers/{customer_id}")
def customer(customer_id: int, session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    _customer(session, customer_id)
    row = customer_service.get_customer(db, customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return {"id": row.id, "name": row.name, "email": row.email}


@router.get("/tickets/customer/{customer_id}")
def tickets(customer_id: int, session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    _customer(session, customer_id)
    rows = ticket_service.get_customer_tickets(db, customer_id)
    return [{"id": r.id, "customer_id": r.customer_id, "order_id": r.order_id,
             "subject": r.subject, "description": r.description, "status": r.status} for r in rows]


@router.get("/customers/{customer_id}/tickets/{ticket_id}")
def ticket(customer_id: int, ticket_id: int, session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    row = _ticket(db, session, ticket_id, customer_id)
    return {"id": row.id, "customer_id": row.customer_id, "order_id": row.order_id,
            "subject": row.subject, "description": row.description, "status": row.status}


@router.get("/customers/{customer_id}/tickets/{ticket_id}/context", response_model=TicketContext)
def ticket_context(customer_id: int, ticket_id: int,
                   session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    row = _ticket(db, session, ticket_id, customer_id)
    customer_row = customer_service.get_customer(db, customer_id)
    order_row = None
    payments = []
    shipments = []
    if row.order_id is not None:
        try:
            lookup_customer_order(db, row.id, row.order_id)
        except ToolAccessError as exc:
            raise HTTPException(status_code=404, detail="Resource not found.") from exc
        order_row = order_service.get_order(db, row.order_id)
        for payment in get_payments_by_order_id(db, row.order_id):
            payments.append(PaymentContext(
                id=payment.id, amount=payment.amount, currency=payment.currency,
                payment_method=payment.payment_method, status=payment.status,
                created_at=payment.created_at,
                refunds=[PaymentRefundContext(
                    id=refund.id, amount=refund.amount, status=refund.status,
                    reason=refund.reason, created_at=refund.created_at,
                ) for refund in get_refund_history(db, payment.id)],
            ))
        shipments = [ShipmentContext(
            id=shipment.id, carrier=shipment.carrier,
            tracking_number=shipment.tracking_number, status=shipment.status,
            estimated_delivery_at=shipment.estimated_delivery_at,
            shipped_at=shipment.shipped_at, delivered_at=shipment.delivered_at,
        ) for shipment in get_shipments_by_order_id(db, row.order_id)]
    return TicketContext(
        customer=customer_row, ticket=row, order=order_row,
        payments=payments, shipments=shipments,
    )


@router.get("/orders/customer/{customer_id}")
def orders(customer_id: int, session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    _customer(session, customer_id)
    rows = order_service.get_customer_orders(db, customer_id)
    return [{"id": r.id, "customer_id": r.customer_id, "status": r.status,
             "items": [{"id": i.id, "product_name": i.product_name, "quantity": i.quantity,
                        "unit_price": i.unit_price} for i in r.items]} for r in rows]


@router.get("/customers/{customer_id}/orders/{order_id}")
def order(customer_id: int, order_id: int, session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    _customer(session, customer_id)
    row = order_service.get_order(db, order_id)
    if row is None or row.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return {"id": row.id, "customer_id": row.customer_id, "status": row.status,
            "items": [{"id": i.id, "product_name": i.product_name, "quantity": i.quantity,
                       "unit_price": i.unit_price} for i in row.items]}


@router.post("/customers/{customer_id}/tickets/{ticket_id}/agent-sessions", response_model=AgentSessionResponse, status_code=201)
async def create_agent_session(customer_id: int, ticket_id: int, body: AgentSessionCreate,
                               request: Request, session: BFFSession = Depends(require_csrf),
                               db: Session = Depends(get_db)):
    _ticket(db, session, ticket_id, customer_id)
    return await _agent_call(request, customer_id, "POST",
                             f"/customers/{customer_id}/tickets/{ticket_id}/agent-sessions", body.model_dump())


@router.post("/customers/{customer_id}/tickets/{ticket_id}/refund-approvals",
             response_model=RefundApprovalResponse, status_code=201)
def create_customer_refund_approval(customer_id: int, ticket_id: int, body: RefundApprovalCreate,
                                    session: BFFSession = Depends(require_csrf),
                                    db: Session = Depends(get_db)):
    if settings.oidc_agent_role not in session.roles:
        raise HTTPException(status_code=403, detail="Support agent access required.")
    row = _ticket(db, session, ticket_id, customer_id)
    if row.order_id is None or row.order_id != body.order_id:
        raise HTTPException(status_code=404, detail="Resource not found.")
    try:
        return refund_approvals.create_refund_approval(
            db, ticket_id, body.order_id, body.payment_id, body.requested_amount,
            body.policy_basis, body.reason, session.subject,
        )
    except refund_approvals.ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc
    except refund_approvals.DuplicateApprovalError as exc:
        raise HTTPException(status_code=409, detail="An active request already exists for this payment.") from exc
    except refund_approvals.RefundEligibilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Refund request could not be created.") from exc


@router.get("/customers/{customer_id}/agent-sessions/{session_id}", response_model=AgentSessionStatus)
async def agent_session(customer_id: int, session_id: int, request: Request,
                        session: BFFSession = Depends(require_user)):
    _customer(session, customer_id)
    return await _agent_call(request, customer_id, "GET", f"/customers/{customer_id}/agent-sessions/{session_id}")


@router.get("/customers/{customer_id}/agent-sessions/{session_id}/messages", response_model=AgentConversation)
async def agent_messages(customer_id: int, session_id: int, request: Request,
                         session: BFFSession = Depends(require_user)):
    _customer(session, customer_id)
    return await _agent_call(request, customer_id, "GET", f"/customers/{customer_id}/agent-sessions/{session_id}/messages")


@router.post("/customers/{customer_id}/agent-sessions/{session_id}/messages", response_model=AgentMessageResult)
async def send_agent_message(customer_id: int, session_id: int, body: AgentMessageCreate,
                             request: Request, session: BFFSession = Depends(require_csrf)):
    _customer(session, customer_id)
    return await _agent_call(request, customer_id, "POST",
                             f"/customers/{customer_id}/agent-sessions/{session_id}/messages", body.model_dump())


@router.get("/customers/{customer_id}/agent-executions/{execution_id}", response_model=AgentExecutionResponse)
async def agent_execution(customer_id: int, execution_id: int, request: Request,
                          session: BFFSession = Depends(require_user)):
    _customer(session, customer_id)
    return await _agent_call(request, customer_id, "GET", f"/customers/{customer_id}/agent-executions/{execution_id}")


@router.get("/customers/{customer_id}/tickets/{ticket_id}/agent-executions", response_model=list[AgentExecutionResponse])
async def ticket_executions(customer_id: int, ticket_id: int, request: Request,
                            session: BFFSession = Depends(require_user), db: Session = Depends(get_db)):
    _ticket(db, session, ticket_id, customer_id)
    return await _agent_call(request, customer_id, "GET", f"/customers/{customer_id}/tickets/{ticket_id}/agent-executions")


@router.post("/customers/{customer_id}/agent-executions/{execution_id}/cancel", response_model=AgentExecutionResponse)
async def cancel_execution(customer_id: int, execution_id: int, request: Request,
                           session: BFFSession = Depends(require_csrf)):
    _customer(session, customer_id)
    return await _agent_call(request, customer_id, "POST", f"/customers/{customer_id}/agent-executions/{execution_id}/cancel", {})


@router.post("/agent-executions/{execution_id}/resume", response_model=AgentExecutionResponse)
def resume_agent_execution(execution_id: int, body: AgentExecutionResume,
                           session: BFFSession = Depends(require_csrf),
                           db: Session = Depends(get_db)):
    if settings.oidc_reviewer_role not in session.roles:
        raise HTTPException(status_code=403, detail="Reviewer access required.")
    try:
        return agent_api.resume_execution_after_approval(db, execution_id, body.approval_id)
    except agent_api.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc
    except agent_api.AgentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except agent_api.AgentAPIError as exc:
        raise HTTPException(status_code=503, detail="Agent execution could not be resumed.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent execution could not be resumed.") from exc


@router.get("/refund-approvals/pending", response_model=list[RefundApprovalResponse])
def pending_approvals(session: BFFSession = Depends(require_reviewer), db: Session = Depends(get_db)):
    try:
        return refund_approvals.list_pending_refund_approvals(db)
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Approval queue is unavailable.") from exc


def _approval_history_response(db: Session, item) -> RefundApprovalHistoryResponse:
    ticket_row = ticket_service.get_ticket(db, item.ticket_id)
    if ticket_row is None:
        raise refund_approvals.ApprovalNotFoundError("Approval ticket was not found.")
    execution_result = None
    if item.status == "executed":
        _, refund = refund_approvals.execute_approved_refund(db, item.id)
        execution_result = RefundExecutionSummary(
            refund_id=refund.id, amount=refund.amount, status=refund.status,
            executed_at=item.executed_at or refund.created_at,
        )
    base = RefundApprovalResponse.model_validate(item)
    return RefundApprovalHistoryResponse(
        **base.model_dump(), customer_id=ticket_row.customer_id,
        ticket_subject=ticket_row.subject, execution_result=execution_result,
    )


@router.get("/customers/{customer_id}/refund-approvals",
            response_model=list[RefundApprovalHistoryResponse])
def customer_refund_approvals(customer_id: int,
                              session: BFFSession = Depends(require_user),
                              db: Session = Depends(get_db)):
    _customer(session, customer_id)
    try:
        approvals = refund_approvals.list_refund_approvals(db, customer_id=customer_id)
        return [_approval_history_response(db, item) for item in approvals]
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Approval history is unavailable.") from exc


@router.get("/refund-approvals/history", response_model=list[RefundApprovalHistoryResponse])
def approval_history(session: BFFSession = Depends(require_reviewer), db: Session = Depends(get_db)):
    try:
        approvals = refund_approvals.list_refund_approvals(db)
        return [_approval_history_response(db, item) for item in approvals]
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Approval history is unavailable.") from exc


@router.get("/refund-approvals/{approval_id}", response_model=RefundApprovalResponse)
def approval(approval_id: int, session: BFFSession = Depends(require_reviewer), db: Session = Depends(get_db)):
    try:
        return refund_approvals.get_refund_approval(db, approval_id)
    except refund_approvals.ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Approval is unavailable.") from exc


@router.post("/refund-approvals/{approval_id}/approve", response_model=RefundApprovalResponse)
def approve(approval_id: int, body: RefundApprovalDecision,
            session: BFFSession = Depends(require_csrf), db: Session = Depends(get_db)):
    if settings.oidc_reviewer_role not in session.roles:
        raise HTTPException(status_code=403, detail="Reviewer access required.")
    try:
        return refund_approvals.approve_refund(db, approval_id, session.subject, body.confirm_policy_review)
    except refund_approvals.ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc
    except refund_approvals.InvalidApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except refund_approvals.RefundEligibilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Approval could not be recorded.") from exc


@router.post("/refund-approvals/{approval_id}/reject", response_model=RefundApprovalResponse)
def reject(approval_id: int, body: RefundRejection,
           session: BFFSession = Depends(require_csrf), db: Session = Depends(get_db)):
    if settings.oidc_reviewer_role not in session.roles:
        raise HTTPException(status_code=403, detail="Reviewer access required.")
    try:
        return refund_approvals.reject_refund(db, approval_id, session.subject, body.reason)
    except refund_approvals.ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc
    except refund_approvals.InvalidApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except refund_approvals.RefundEligibilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Rejection could not be recorded.") from exc


@router.post("/refund-approvals/{approval_id}/execute", response_model=RefundExecutionResult)
def execute_approval(approval_id: int, session: BFFSession = Depends(require_csrf),
                     db: Session = Depends(get_db)):
    if settings.oidc_reviewer_role not in session.roles:
        raise HTTPException(status_code=403, detail="Reviewer access required.")
    try:
        approval, refund = refund_approvals.execute_approved_refund(db, approval_id)
        return RefundExecutionResult(
            approval=approval, refund_id=refund.id, payment_id=refund.payment_id,
            amount=refund.amount, status=refund.status, reason=refund.reason,
            idempotency_key=refund.idempotency_key, created_at=refund.created_at,
        )
    except refund_approvals.ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc
    except refund_approvals.InvalidApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except refund_approvals.RefundEligibilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Refund execution could not be completed.") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Refund execution could not be completed.") from exc


@router.get("/refund-approvals/{approval_id}/execution", response_model=RefundExecutionResult)
def refund_execution_result(approval_id: int, session: BFFSession = Depends(require_reviewer),
                            db: Session = Depends(get_db)):
    try:
        approval = refund_approvals.get_refund_approval(db, approval_id)
        if approval.status != "executed" or approval.refund_id is None:
            raise HTTPException(status_code=404, detail="Execution result not found.")
        approval, refund = refund_approvals.execute_approved_refund(db, approval_id)
        return RefundExecutionResult(approval=approval, refund_id=refund.id, payment_id=refund.payment_id,
                                    amount=refund.amount, status=refund.status, reason=refund.reason,
                                    idempotency_key=refund.idempotency_key, created_at=refund.created_at)
    except refund_approvals.ApprovalError as exc:
        raise HTTPException(status_code=503, detail="Execution result could not be verified.") from exc
