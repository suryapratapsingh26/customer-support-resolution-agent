import asyncio

from app.config import settings
from app.auth import oidc


def test_keycloak_discovery_keeps_browser_urls_public_and_moves_backchannel_internal(monkeypatch):
    issuer = "http://localhost:8081/realms/customer-support-dev"
    internal = "http://keycloak:8080"
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "oidc_issuer", issuer)
    monkeypatch.setattr(settings, "oidc_audience", "support-dashboard")
    monkeypatch.setattr(settings, "oidc_client_id", "support-dashboard")
    monkeypatch.setattr(settings, "oidc_client_secret", "local-client-secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "http://localhost:8080/api/bff/auth/callback")
    monkeypatch.setattr(settings, "oidc_backchannel_base_url", internal)

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/protocol/openid-connect/auth",
                "token_endpoint": f"{issuer}/protocol/openid-connect/token",
                "jwks_uri": f"{issuer}/protocol/openid-connect/certs",
            }

    class AsyncClient:
        requested_url = None

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            type(self).requested_url = url
            return Response()

    monkeypatch.setattr(oidc.httpx, "AsyncClient", AsyncClient)
    discovery = asyncio.run(oidc._discovery())

    assert AsyncClient.requested_url == (
        "http://keycloak:8080/realms/customer-support-dev/.well-known/openid-configuration"
    )
    assert discovery["issuer"] == issuer
    assert discovery["authorization_endpoint"].startswith("http://localhost:8081/")
    assert discovery["token_endpoint"] == f"{internal}/realms/customer-support-dev/protocol/openid-connect/token"
    assert discovery["jwks_uri"] == f"{internal}/realms/customer-support-dev/protocol/openid-connect/certs"
    assert oidc._secure_endpoint(discovery["jwks_uri"])
    assert not oidc._browser_endpoint(discovery["token_endpoint"])
    assert not oidc._secure_endpoint("http://attacker:8080/keys")

