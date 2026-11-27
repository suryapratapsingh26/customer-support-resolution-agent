import pytest
from fastapi import HTTPException

from app.config import Settings
from app import main


def _production_settings(**overrides):
    values = {
        "environment": "production",
        "database_url": "postgresql+psycopg://support:password@postgres:5432/support",
        "oidc_issuer": "https://id.example.test",
        "oidc_audience": "support-dashboard",
        "oidc_client_id": "support-dashboard",
        "oidc_client_secret": "f" * 40,
        "oidc_redirect_uri": "https://support.example.test/api/bff/auth/callback",
        "backend_service_api_key": "a" * 40,
        "agent_api_key": "b" * 40,
        "agent_customer_token_secret": "c" * 40,
        "approval_api_key": "d" * 40,
        "approval_request_api_key": "e" * 40,
        "approval_actor_id": "refund-reviewer",
        "approval_request_actor_id": "refund-requester",
        "llm_api_key": "g" * 40,
        "bff_session_cookie_secure": True,
        "bff_trusted_origins": ["https://support.example.test"],
    }
    values.update(overrides)
    return Settings(**values)


def test_production_configuration_accepts_complete_secure_setup():
    _production_settings().validate_runtime()


@pytest.mark.parametrize("override,expected", [
    ({"bff_session_cookie_secure": False}, "BFF_SESSION_COOKIE_SECURE"),
    ({"oidc_redirect_uri": "http://support.example.test/api/bff/auth/callback"}, "OIDC_REDIRECT_URI"),
    ({"bff_trusted_origins": ["http://support.example.test"]}, "BFF_TRUSTED_ORIGINS"),
    ({"agent_api_key": "short"}, "AGENT_API_KEY"),
    ({"approval_api_key": "e" * 40}, "must differ"),
    ({"approval_request_actor_id": "refund-reviewer"}, "identities must differ"),
    ({"agent_api_key": "a" * 40}, "credentials and signing secrets must be distinct"),
    ({"llm_base_url": "http://llm.example.test/v1"}, "LLM_BASE_URL"),
    ({"oidc_allowed_algorithms": ["HS256"]}, "asymmetric signing algorithms"),
    ({"oidc_backchannel_base_url": "http://keycloak:8080"}, "OIDC_BACKCHANNEL_BASE_URL"),
    ({"oidc_roles_claim": ""}, "claim names are required"),
    ({"database_url": "sqlite:///prod.db"}, "DATABASE_URL"),
])
def test_production_configuration_rejects_missing_or_insecure_settings(override, expected):
    with pytest.raises(ValueError, match=expected):
        _production_settings(**override).validate_runtime()


def test_development_configuration_keeps_local_http_defaults():
    Settings(environment="development", database_url="sqlite:///local.db").validate_runtime()


def test_readiness_returns_generic_unavailable_response_when_database_fails(monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("contains-internal-database-details")

    monkeypatch.setattr(main, "engine", BrokenEngine())
    with pytest.raises(HTTPException) as error:
        main.readiness()
    assert error.value.status_code == 503
    assert "contains-internal" not in str(error.value.detail)


def test_configured_http_access_logs_suppress_customer_paths():
    main.configure_logging()
    assert main.logging.getLogger("httpx").level >= main.logging.WARNING
    assert main.logging.getLogger("httpcore").level >= main.logging.WARNING
    assert main.logging.getLogger("uvicorn.access").level >= main.logging.WARNING
