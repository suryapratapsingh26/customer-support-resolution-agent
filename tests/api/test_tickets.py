from app.db.models import Order, Ticket
from app.db.session import get_db
from app.main import app


def create_test_ticket(client):
    customer_response = client.post(
        "/api/v1/customers/",
        json={"name": "John Doe", "email": "john@example.com"},
    )
    customer_id = customer_response.json()["id"]

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        ticket = Ticket(
            customer_id=customer_id,
            subject="Delayed delivery",
            description="My order has not arrived.",
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        return ticket.id
    finally:
        db_generator.close()


def test_create_ticket(client):
    customer_response = client.post(
        "/api/v1/customers/",
        json={"name": "John Doe", "email": "john@example.com"},
    )
    customer_id = customer_response.json()["id"]

    response = client.post(
        "/api/v1/tickets/",
        json={
            "customer_id": customer_id,
            "subject": "Delayed delivery",
            "description": "My order has not arrived.",
        },
    )

    assert response.status_code == 201
    assert response.json()["subject"] == "Delayed delivery"
    assert response.json()["status"] == "open"


def test_get_ticket(client):
    ticket_id = create_test_ticket(client)

    response = client.get(f"/api/v1/tickets/{ticket_id}")

    assert response.status_code == 200
    assert response.json()["id"] == ticket_id


def test_get_nonexistent_ticket(client):
    response = client.get("/api/v1/tickets/999")

    assert response.status_code == 404


def test_get_customer_tickets(client):
    ticket_id = create_test_ticket(client)

    response = client.get("/api/v1/tickets/customer/1")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == ticket_id


def test_update_ticket(client):
    ticket_id = create_test_ticket(client)

    response = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "in_progress"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_create_ticket_with_nonexistent_customer(client):
    response = client.post(
        "/api/v1/tickets/",
        json={
            "customer_id": 999,
            "subject": "Delivery issue",
            "description": "Order not received.",
        },
    )

    assert response.status_code == 404


def test_create_ticket_with_nonexistent_order(client):
    customer_response = client.post(
        "/api/v1/customers/",
        json={"name": "John Doe", "email": "john@example.com"},
    )
    customer_id = customer_response.json()["id"]

    response = client.post(
        "/api/v1/tickets/",
        json={
            "customer_id": customer_id,
            "order_id": 999,
            "subject": "Delivery issue",
            "description": "Order not received.",
        },
    )

    assert response.status_code == 404


def test_create_ticket_with_another_customers_order(client):
    first_customer = client.post(
        "/api/v1/customers/",
        json={"name": "John Doe", "email": "john@example.com"},
    ).json()

    second_customer = client.post(
        "/api/v1/customers/",
        json={"name": "Jane Doe", "email": "jane@example.com"},
    ).json()

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        order = Order(
            customer_id=first_customer["id"],
            status="confirmed",
        )
        db.add(order)
        db.commit()
        order_id = order.id
    finally:
        db_generator.close()

    response = client.post(
        "/api/v1/tickets/",
        json={
            "customer_id": second_customer["id"],
            "order_id": order_id,
            "subject": "Delivery issue",
            "description": "Order not received.",
        },
    )

    assert response.status_code == 400