from fastapi import APIRouter

from app.api.v1.routes import customers, knowledge, orders, refund_approvals, tickets


api_router = APIRouter(prefix="/api/v1")

api_router.include_router(customers.router)
api_router.include_router(orders.router)
api_router.include_router(tickets.router)
api_router.include_router(knowledge.router)
api_router.include_router(refund_approvals.router)
