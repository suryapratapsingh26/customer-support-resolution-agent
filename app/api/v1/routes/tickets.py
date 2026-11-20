from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Customer, Order
from app.db.session import get_db
from app.schemas.ticket import TicketCreate, TicketResponse, TicketUpdate
from app.schemas.resolution import ResolutionRecommendation
from app.agents.workflow import TicketNotFoundError, WorkflowError, run_resolution_workflow
from app.services import ticket as ticket_service


router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.post("/{ticket_id}/resolution-recommendation", response_model=ResolutionRecommendation)
def recommend_resolution(ticket_id: int, db: Session = Depends(get_db)):
    try:
        return run_resolution_workflow(ticket_id, db)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.") from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Resolution recommendation is temporarily unavailable.") from exc
    except Exception as exc:
        # Do not leak provider, database, or configuration details to API clients.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Resolution recommendation is temporarily unavailable.") from exc


@router.post(
    "/",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ticket(
    ticket_data: TicketCreate,
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, ticket_data.customer_id)

    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found.",
        )

    if ticket_data.order_id is not None:
        order = db.get(Order, ticket_data.order_id)

        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )

        if order.customer_id != ticket_data.customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order does not belong to the specified customer.",
            )

    return ticket_service.create_ticket(db, ticket_data)


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
):
    ticket = ticket_service.get_ticket(db, ticket_id)

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    return ticket


@router.get(
    "/customer/{customer_id}",
    response_model=list[TicketResponse],
)
def get_customer_tickets(
    customer_id: int,
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, customer_id)

    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found.",
        )

    return ticket_service.get_customer_tickets(db, customer_id)


@router.patch("/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: Session = Depends(get_db),
):
    ticket = ticket_service.get_ticket(db, ticket_id)

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    return ticket_service.update_ticket(db, ticket, ticket_data)
