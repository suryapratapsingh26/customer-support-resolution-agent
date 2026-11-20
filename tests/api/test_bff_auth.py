import hashlib
import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import settings
from app.db.models import BFFSession, Customer
from app.db.session import get_db
from app.main import app
from app.auth import oidc


def _insert_session(customer_ids, roles=("support_agent",), subject="agent-1"):
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    raw_token = "test-bff-session-cookie-value"
    session = BFFSession(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), subject=subject,
        roles=list(roles), customer_ids=list(customer_ids), csrf_token="csrf-test-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(session)
    db.commit()
    db_generator.close()
    return raw_token


def _create_customer(client, email):
    response = client.post("/api/v1/customers/", json={"name": "BFF Customer", "email": email})
    assert response.status_code == 201
    return response.json()["id"]


def test_bff_requires_session_and_limits_customer_scope(client):
    first_id = _create_customer(client, "bff-first@example.test")
    second_id = _create_customer(client, "bff-second@example.test")
    assert client.get("/api/bff/customers").status_code == 401

    client.cookies.set(settings.bff_session_cookie_name, _insert_session([first_id]))
    assert [row["id"] for row in client.get("/api/bff/customers").json()] == [first_id]
    assert client.get(f"/api/bff/customers/{second_id}").status_code == 404
    assert client.get(f"/api/bff/tickets/customer/{second_id}").status_code == 404
    assert client.get(f"/api/bff/orders/customer/{second_id}").status_code == 404


def test_bff_state_changes_require_origin_and_csrf(client):
    client.cookies.set(settings.bff_session_cookie_name, _insert_session([]))
    url = "/api/bff/auth/logout"
    assert client.post(url).status_code == 403
    origin = settings.bff_trusted_origins[0] if settings.bff_trusted_origins else "http://localhost:5173"
    assert client.post(url, headers={"Origin": origin, "X-CSRF-Token": "wrong"}).status_code == 403

    previous_origins = settings.bff_trusted_origins
    settings.bff_trusted_origins = [origin]
    try:
        response = client.post(url, headers={"Origin": origin, "X-CSRF-Token": "csrf-test-token"})
        assert response.status_code == 204
        assert client.get("/api/bff/auth/status").json()["authenticated"] is False
    finally:
        settings.bff_trusted_origins = previous_origins


def test_reviewer_routes_require_reviewer_role(client):
    client.cookies.set(settings.bff_session_cookie_name, _insert_session([], roles=("support_agent",)))
    assert client.get("/api/bff/refund-approvals/pending").status_code == 403


def test_browser_cannot_use_internal_customer_api_with_invalid_service_credential(client):
    response = client.get("/api/v1/customers/", headers={"X-Backend-Service-Token": "invalid"})
    assert response.status_code == 401


def test_bff_rejects_expired_session(client):
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    raw_token = "expired-bff-session-cookie-value"
    db.add(BFFSession(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), subject="agent-1",
        roles=["support_agent"], customer_ids=[], csrf_token="csrf",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    ))
    db.commit()
    db_generator.close()
    client.cookies.set(settings.bff_session_cookie_name, raw_token)
    assert client.get("/api/bff/auth/status").json()["authenticated"] is False


def test_oidc_state_is_bound_to_the_login_browser(client, monkeypatch):
    previous = {
        "oidc_issuer": settings.oidc_issuer, "oidc_audience": settings.oidc_audience,
        "oidc_client_id": settings.oidc_client_id, "oidc_client_secret": settings.oidc_client_secret,
        "oidc_redirect_uri": settings.oidc_redirect_uri,
    }
    settings.oidc_issuer = "https://identity.example.test"
    settings.oidc_audience = "support-dashboard"
    settings.oidc_client_id = "support-dashboard"
    settings.oidc_client_secret = "test-secret"
    settings.oidc_redirect_uri = "https://support.example.test/api/bff/auth/callback"

    async def discovery():
        return {"issuer": settings.oidc_issuer,
                "authorization_endpoint": "https://identity.example.test/authorize",
                "token_endpoint": "https://identity.example.test/token",
                "jwks_uri": "https://identity.example.test/jwks"}

    monkeypatch.setattr(oidc, "_discovery", discovery)
    try:
        db_generator = app.dependency_overrides[get_db]()
        db = next(db_generator)
        login_url, binding = asyncio.run(oidc.begin_login(db))
        state = parse_qs(urlsplit(login_url).query)["state"][0]
        with pytest.raises(oidc.OIDCError):
            asyncio.run(oidc.complete_login(db, "authorization-code", state, "attacker-browser"))
        db_generator.close()
        assert binding != "attacker-browser"
    finally:
        for name, value in previous.items():
            setattr(settings, name, value)


def test_oidc_verifies_audience_issuer_and_customer_claims(client, monkeypatch):
    previous = {name: getattr(settings, name) for name in (
        "oidc_issuer", "oidc_audience", "oidc_client_id", "oidc_client_secret", "oidc_redirect_uri",
    )}
    settings.oidc_issuer = "https://identity.example.test"
    settings.oidc_audience = "support-dashboard"
    settings.oidc_client_id = "support-dashboard"
    settings.oidc_client_secret = "test-secret"
    settings.oidc_redirect_uri = "https://support.example.test/api/bff/auth/callback"

    async def discovery():
        return {"issuer": settings.oidc_issuer,
                "authorization_endpoint": "https://identity.example.test/authorize",
                "token_endpoint": "https://identity.example.test/token",
                "jwks_uri": "https://identity.example.test/jwks"}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id_token": "signed-id-token"}

    class AsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            assert url == "https://identity.example.test/token"
            assert kwargs["auth"] == ("support-dashboard", "test-secret")
            return Response()

    async def discovery_only():
        return await discovery()

    monkeypatch.setattr(oidc, "_discovery", discovery_only)
    monkeypatch.setattr(oidc.httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(oidc.jwt, "PyJWKClient", lambda *args, **kwargs: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key="verified-key")))
    decoded = {}
    claims_holder = {"roles": ["support_agent"], "customer_ids": [4, 9]}

    def decode(token, key, **kwargs):
        decoded.update(kwargs)
        return {"sub": "operator-4", "nonce": expected_nonce, "iss": settings.oidc_issuer,
                "aud": settings.oidc_audience, "exp": 4_000_000_000, "iat": 1_800_000_000,
                **claims_holder}

    monkeypatch.setattr(oidc.jwt, "decode", decode)
    db_generator = None
    try:
        db_generator = app.dependency_overrides[get_db]()
        db = next(db_generator)
        login_url, browser_binding = asyncio.run(oidc.begin_login(db))
        state = parse_qs(urlsplit(login_url).query)["state"][0]
        expected_nonce = db.query(oidc.BFFLoginAttempt).one().nonce
        session, raw_cookie = asyncio.run(oidc.complete_login(db, "authorization-code", state, browser_binding))
        assert session.subject == "operator-4"
        assert session.customer_ids == [4, 9]
        assert raw_cookie
        assert session.token_hash == hashlib.sha256(raw_cookie.encode()).hexdigest()
        assert decoded["algorithms"] == ["RS256"]
        assert decoded["issuer"] == settings.oidc_issuer
        assert decoded["audience"] == settings.oidc_audience
        assert {"iss", "aud", "exp", "iat", "sub"} <= set(decoded["options"]["require"])

        claims_holder["azp"] = "different-client"
        login_url, browser_binding = asyncio.run(oidc.begin_login(db))
        state = parse_qs(urlsplit(login_url).query)["state"][0]
        expected_nonce = db.query(oidc.BFFLoginAttempt).one().nonce
        with pytest.raises(oidc.OIDCError, match="authorized party"):
            asyncio.run(oidc.complete_login(db, "authorization-code", state, browser_binding))

        claims_holder.pop("azp")
        claims_holder["aud"] = [settings.oidc_audience, "another-audience"]
        login_url, browser_binding = asyncio.run(oidc.begin_login(db))
        state = parse_qs(urlsplit(login_url).query)["state"][0]
        expected_nonce = db.query(oidc.BFFLoginAttempt).one().nonce
        with pytest.raises(oidc.OIDCError, match="authorized party"):
            asyncio.run(oidc.complete_login(db, "authorization-code", state, browser_binding))
    finally:
        if db_generator is not None:
            db_generator.close()
        for key, value in previous.items():
            setattr(settings, key, value)


def test_non_development_rejects_insecure_session_cookie():
    previous_environment = settings.environment
    previous_secure = settings.bff_session_cookie_secure
    settings.environment = "production"
    settings.bff_session_cookie_secure = False
    try:
        with pytest.raises(oidc.HTTPException, match="cookie security"):
            oidc._configured()
    finally:
        settings.environment = previous_environment
        settings.bff_session_cookie_secure = previous_secure

