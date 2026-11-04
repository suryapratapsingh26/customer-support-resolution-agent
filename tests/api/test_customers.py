def test_create_customer(client):
    response = client.post(
        "/api/v1/customers/",
        json={
            "name": "John Doe",
            "email": "john@example.com",
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["id"] == 1
    assert data["name"] == "John Doe"
    assert data["email"] == "john@example.com"


def test_list_customers(client):
    client.post(
        "/api/v1/customers/",
        json={"name": "John Doe", "email": "john@example.com"},
    )

    response = client.get("/api/v1/customers/")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_customer(client):
    create_response = client.post(
        "/api/v1/customers/",
        json={"name": "John Doe", "email": "john@example.com"},
    )
    customer_id = create_response.json()["id"]

    response = client.get(f"/api/v1/customers/{customer_id}")

    assert response.status_code == 200
    assert response.json()["name"] == "John Doe"


def test_get_nonexistent_customer(client):
    response = client.get("/api/v1/customers/999")

    assert response.status_code == 404


def test_create_customer_with_duplicate_email(client):
    payload = {"name": "John Doe", "email": "john@example.com"}

    client.post("/api/v1/customers/", json=payload)
    response = client.post("/api/v1/customers/", json=payload)

    assert response.status_code == 409