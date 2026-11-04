from app.db.models import Order, OrderItem
from app.db.session import get_db
from app.main import app


def create_test_order(client):
    customer_response = client.post(
        "/api/v1/customers/",
        json={"name": "John Doe", "email": "john@example.com"},
    )
    customer_id = customer_response.json()["id"]

    override_get_db = app.dependency_overrides[get_db]
    db_generator = override_get_db()
    db = next(db_generator)

    try:
        order = Order(customer_id=customer_id, status="confirmed")
        db.add(order)
        db.flush()

        db.add(
            OrderItem(
                order_id=order.id,
                product_name="Laptop",
                quantity=1,
                unit_price=75000,
            )
        )
        db.commit()

        return order.id
    finally:
        db_generator.close()


def test_get_order_with_items(client):
    order_id = create_test_order(client)

    response = client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["items"][0]["product_name"] == "Laptop"


def test_get_nonexistent_order(client):
    response = client.get("/api/v1/orders/999")

    assert response.status_code == 404


def test_get_customer_orders(client):
    order_id = create_test_order(client)

    response = client.get(
        f"/api/v1/orders/customer/1"
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == order_id