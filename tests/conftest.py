import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Customer, Order, OrderItem, Ticket
from app.db.session import get_db
from app.main import app
from app.config import settings


@pytest.fixture
def client():
    auth_setting_names = (
        "backend_service_api_key", "agent_api_key", "agent_customer_token_secret",
        "approval_api_key", "approval_actor_id", "approval_request_api_key",
        "approval_request_actor_id", "oidc_issuer", "oidc_audience", "oidc_client_id",
        "oidc_client_secret", "oidc_redirect_uri", "oidc_jwks_url",
        "oidc_backchannel_base_url", "bff_trusted_origins", "environment",
        "oidc_roles_claim", "oidc_customer_ids_claim", "oidc_reviewer_role",
        "oidc_agent_role", "oidc_allowed_algorithms",
    )
    previous_auth_settings = {name: getattr(settings, name) for name in auth_setting_names}
    test_auth_settings = {
        "environment": "development",
        "bff_trusted_origins": [],
        "oidc_roles_claim": "roles",
        "oidc_customer_ids_claim": "customer_ids",
        "oidc_reviewer_role": "support_reviewer",
        "oidc_agent_role": "support_agent",
        "oidc_allowed_algorithms": ["RS256"],
    }
    for name in auth_setting_names:
        setattr(settings, name, test_auth_settings.get(name))
    settings.backend_service_api_key = "test-backend-service-token-012345678901"
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, headers={"X-Backend-Service-Token": settings.backend_service_api_key}) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    for name, value in previous_auth_settings.items():
        setattr(settings, name, value)
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
