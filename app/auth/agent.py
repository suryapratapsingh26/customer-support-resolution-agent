import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException, status

from app.config import settings


def require_agent_service(x_agent_api_key: str | None = Header(default=None)) -> None:
    expected = settings.agent_api_key
    if not expected or len(expected.strip()) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent API is not configured.",
        )
    if not x_agent_api_key or not secrets.compare_digest(x_agent_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent API authentication required.",
        )


def create_customer_scope_token(customer_id: int, *, expires_at: int) -> str:
    """Create a short-lived scope token for a trusted upstream identity service."""
    secret = settings.agent_customer_token_secret
    if not secret or len(secret.strip()) < 32:
        raise RuntimeError("Agent customer token signing is not configured.")
    payload = f"{customer_id}.{expires_at}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def require_agent_customer(
    customer_id: int,
    x_agent_api_key: str | None = Header(default=None),
    x_agent_customer_token: str | None = Header(default=None),
) -> None:
    """Authenticate the service and bind its request to one customer identity."""
    require_agent_service(x_agent_api_key)
    secret = settings.agent_customer_token_secret
    if not secret or len(secret.strip()) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent customer authorization is not configured.",
        )
    try:
        token_customer, token_expiry, signature = (x_agent_customer_token or "").split(".")
        token_customer_id = int(token_customer)
        expires_at = int(token_expiry)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Customer-scoped agent authorization required.") from None
    payload = f"{token_customer_id}.{expires_at}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    now = int(time.time())
    if (
        token_customer_id != customer_id
        or expires_at <= now
        or expires_at > now + 600
        or not secrets.compare_digest(signature, expected)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Customer-scoped agent authorization required.")
