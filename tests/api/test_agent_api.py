import time

from app.config import settings
from app.auth.agent import create_customer_scope_token
from app.schemas.resolution import KnowledgeSource, ResolutionRecommendation


def headers(customer_id):
    return {
        "X-Agent-API-Key": "a" * 40,
        "X-Agent-Customer-Token": create_customer_scope_token(
            customer_id, expires_at=int(time.time()) + 120
        ),
    }


def test_agent_api_auth_ownership_and_conversation(client, monkeypatch):
    monkeypatch.setattr(settings, "agent_api_key", "a" * 40)
    monkeypatch.setattr(settings, "agent_customer_token_secret", "s" * 40)
    assert client.post(
        "/api/v1/customers/1/tickets/1/agent-sessions",
        json={"idempotency_key": "session-api-key-1"},
    ).status_code == 401

    customer = client.post("/api/v1/customers/", json={
        "name": "Casey", "email": "casey-api@example.test",
    }).json()
    ticket = client.post("/api/v1/tickets/", json={
        "customer_id": customer["id"], "subject": "Delivery", "description": "Where is it?",
    }).json()
    other = client.post("/api/v1/customers/", json={
        "name": "Other", "email": "other-api@example.test",
    }).json()

    no_customer_scope = client.post(
        f"/api/v1/customers/{customer['id']}/tickets/{ticket['id']}/agent-sessions",
        headers={"X-Agent-API-Key": "a" * 40},
        json={"idempotency_key": "session-api-key-2"},
    )
    assert no_customer_scope.status_code == 401

    created = client.post(
        f"/api/v1/customers/{customer['id']}/tickets/{ticket['id']}/agent-sessions",
        headers=headers(customer["id"]), json={"idempotency_key": "session-api-key-2"},
    )
    assert created.status_code == 201
    session_id = created.json()["id"]
    replay = client.post(
        f"/api/v1/customers/{customer['id']}/tickets/{ticket['id']}/agent-sessions",
        headers=headers(customer["id"]), json={"idempotency_key": "session-api-key-2"},
    )
    assert replay.status_code == 200 and replay.json()["id"] == session_id

    wrong_scope = client.get(
        f"/api/v1/customers/{customer['id']}/agent-sessions/{session_id}",
        headers=headers(other["id"]),
    )
    assert wrong_scope.status_code == 401

    hidden = client.get(
        f"/api/v1/customers/{other['id']}/agent-sessions/{session_id}", headers=headers(other["id"])
    )
    assert hidden.status_code == 404
    history = client.get(
        f"/api/v1/customers/{customer['id']}/agent-sessions/{session_id}/messages",
        headers=headers(customer["id"]),
    )
    assert history.status_code == 200 and history.json()["messages"] == []

    monkeypatch.setattr(
        "app.services.agent_api.run_resolution_workflow",
        lambda *args, **kwargs: ResolutionRecommendation(
            ticket_id=ticket["id"], issue_category="shipping", issue_summary="Delivery",
            customer_context_summary="Order available.", retrieved_knowledge_sources=[KnowledgeSource(
                id="policy-7", document_id="shipping", document_name="Shipping policy",
                category="shipping", text="Tracking can be delayed by the carrier.", distance=0.2,
            )], proposed_resolution="Check the shipment.",
            explanation="The support team can check the shipment status.", confidence_score=0.8,
        ),
    )
    submitted = client.post(
        f"/api/v1/customers/{customer['id']}/agent-sessions/{session_id}/messages",
        headers=headers(customer["id"]), json={"content": "Can you check?", "idempotency_key": "message-api-key-1"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["execution"]["status"] == "completed"
    assert submitted.json()["execution"]["recommendation"]["retrieved_knowledge_sources"][0]["document_name"] == "Shipping policy"
    history = client.get(
        f"/api/v1/customers/{customer['id']}/agent-sessions/{session_id}/messages",
        headers=headers(customer["id"]),
    )
    assert [message["role"] for message in history.json()["messages"]] == ["customer", "assistant"]


def test_resume_requires_separate_approval_operator_credential(client, monkeypatch):
    monkeypatch.setattr(settings, "approval_request_api_key", "r" * 40)
    monkeypatch.setattr(settings, "approval_api_key", "v" * 40)
    monkeypatch.setattr(settings, "approval_request_actor_id", "intake-service")
    monkeypatch.setattr(settings, "approval_actor_id", "reviewer")
    path = "/api/v1/agent-executions/1/resume"
    payload = {"approval_id": 1}
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, headers={"X-Approval-Token": "r" * 40}, json=payload).status_code == 401
