from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Order


def get_order(db: Session, order_id: int) -> Order | None:
    statement = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id)
    )
    return db.scalars(statement).first()


def get_customer_orders(db: Session, customer_id: int) -> list[Order]:
    statement = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.customer_id == customer_id)
        .order_by(Order.id)
    )
    return list(db.scalars(statement).all())