from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer
from app.schemas.customer import CustomerCreate


def create_customer(db: Session, customer_data: CustomerCreate) -> Customer:
    customer = Customer(**customer_data.model_dump())

    db.add(customer)
    db.commit()
    db.refresh(customer)

    return customer


def get_customer(db: Session, customer_id: int) -> Customer | None:
    return db.get(Customer, customer_id)


def get_customers(db: Session) -> list[Customer]:
    statement = select(Customer).order_by(Customer.id)
    return list(db.scalars(statement).all())