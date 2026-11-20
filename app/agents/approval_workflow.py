"""DB-backed pause/resume graph for approved refund execution."""

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RefundApproval
from app.services.refund_approvals import (
    ApprovalNotFoundError,
    InvalidApprovalTransitionError,
    execute_approved_refund,
)


class RefundExecutionState(TypedDict, total=False):
    approval_id: int
    status: str
    approval: Any
    refund: Any


def build_refund_execution_workflow(db: Session):
    def load_approval(state: RefundExecutionState) -> dict:
        approval = db.scalar(
            select(RefundApproval).where(RefundApproval.id == state["approval_id"])
            .execution_options(populate_existing=True)
        )
        if approval is None:
            raise ApprovalNotFoundError("Refund approval was not found.")
        return {"approval": approval, "status": approval.status}

    def route(state: RefundExecutionState) -> str:
        if state["status"] in {"approved", "executed"}:
            return "execute_or_resume"
        return "paused"

    def execute(state: RefundExecutionState) -> dict:
        approval, refund = execute_approved_refund(db, state["approval_id"])
        return {"approval": approval, "refund": refund, "status": approval.status}

    graph = StateGraph(RefundExecutionState)
    graph.add_node("load_approval", load_approval)
    graph.add_node("execute_or_resume", execute)
    graph.set_entry_point("load_approval")
    graph.add_conditional_edges(
        "load_approval", route,
        {"execute_or_resume": "execute_or_resume", "paused": END},
    )
    graph.add_edge("execute_or_resume", END)
    return graph.compile()


def resume_refund_workflow(approval_id: int, db: Session):
    """Re-read durable approval state on every resume; never trust saved graph state."""
    result = build_refund_execution_workflow(db).invoke({"approval_id": approval_id})
    if result["status"] not in {"approved", "executed"}:
        raise InvalidApprovalTransitionError(
            f"Refund execution is paused while approval is {result['status']}."
        )
    return result["approval"], result["refund"]
