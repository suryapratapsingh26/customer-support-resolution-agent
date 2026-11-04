from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate


def create_ticket(db: Session, ticket_data: TicketCreate) -> Ticket:
    ticket = Ticket(**ticket_data.model_dump())

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return ticket


def get_ticket(db: Session, ticket_id: int) -> Ticket | None:
    return db.get(Ticket, ticket_id)


def get_customer_tickets(db: Session, customer_id: int) -> list[Ticket]:
    statement = (
        select(Ticket)
        .where(Ticket.customer_id == customer_id)
        .order_by(Ticket.id)
    )
    return list(db.scalars(statement).all())


def update_ticket(
    db: Session,
    ticket: Ticket,
    ticket_data: TicketUpdate,
) -> Ticket:
    updates = ticket_data.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(ticket, field, value)

    db.commit()
    db.refresh(ticket)

    return ticket