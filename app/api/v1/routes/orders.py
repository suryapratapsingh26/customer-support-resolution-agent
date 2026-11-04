from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.order import OrderResponse
from app.services import order as order_service


router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
):
    order = order_service.get_order(db, order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    return order


@router.get(
    "/customer/{customer_id}",
    response_model=list[OrderResponse],
)
def get_customer_orders(
    customer_id: int,
    db: Session = Depends(get_db),
):
    return order_service.get_customer_orders(db, customer_id)