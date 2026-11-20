import secrets

from fastapi import Header, HTTPException, status

from app.config import settings


def require_backend_service(x_backend_service_token: str | None = Header(default=None)) -> None:
    expected = settings.backend_service_api_key
    if not expected or len(expected.strip()) < 32:
        raise HTTPException(status_code=503, detail="Backend service authentication is not configured.")
    if not x_backend_service_token or not secrets.compare_digest(x_backend_service_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Service authentication required.")
